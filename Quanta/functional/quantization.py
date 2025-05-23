"""
Quantization and dequantization functions.
"""

import torch

def quantize_4bit(tensor, quant_type="linear", per_channel=False):
    """
    Quantize a floating-point tensor to 4-bit precision.
    """
    if quant_type == "linear":
        return quantize_4bit_linear(tensor, per_channel)
    elif quant_type == "nf4":
        return quantize_4bit_nf4(tensor)
    elif quant_type == "fp4":
        return quantize_4bit_fp4(tensor)
    else:
        raise ValueError(f"Unknown quantization type: {quant_type}")

def quantize_8bit(tensor, quant_type="linear", per_channel=False):
    """
    Quantize a floating-point tensor to 8-bit precision.
    """
    if quant_type == "linear":
        return quantize_8bit_linear(tensor, per_channel)
    elif quant_type == "nf8":
        return quantize_8bit_nf8(tensor)
    elif quant_type == "fp8":
        return quantize_8bit_fp8(tensor)
    else:
        raise ValueError(f"Unknown quantization type: {quant_type}")

def dequantize_8bit(q_tensor, scale_or_levels, zero_point_or_bias, quant_type="linear"):
    """
    Dequantize an 8-bit tensor back to floating point.
    """
    if quant_type == "linear":
        return q_tensor.float() * scale_or_levels + zero_point_or_bias
    elif quant_type == "nf8":
        # scale_or_levels is the nf8_levels tensor
        return scale_or_levels[q_tensor.long()] * zero_point_or_bias
    elif quant_type == "fp8":
        # Convert to uint8 for bitwise operations
        q_tensor = q_tensor.to(torch.uint8)
        signs = torch.where(q_tensor & 0x80, -1.0, 1.0)
        exp_values = (q_tensor >> 3) & 0x0F
        mantissa_values = q_tensor & 0x07
        values = (1.0 + mantissa_values.float() / 8.0) * (2.0 ** (exp_values.float() - zero_point_or_bias))
        return values * signs
    else:
        raise ValueError(f"Unknown quantization type: {quant_type}")

def dequantize_4bit(q_tensor, scale_or_levels, zero_point_or_bias, quant_type="linear"):
    """
    Dequantize a 4-bit tensor back to floating point.
    """
    if quant_type == "linear":
        return q_tensor.float() * scale_or_levels + zero_point_or_bias
    elif quant_type == "nf4":
        # scale_or_levels is the nf4_levels tensor
        return scale_or_levels[q_tensor.long()] * zero_point_or_bias
    elif quant_type == "fp4":
        # Convert to uint8 for bitwise operations
        q_tensor = q_tensor.to(torch.uint8)
        signs = torch.where(q_tensor & 0x8, -1.0, 1.0)
        exp_values = (q_tensor >> 1) & 0x3
        mantissa_values = q_tensor & 0x1
        values = (1.0 + mantissa_values.float()) * (2.0 ** (exp_values.float() - zero_point_or_bias))
        return values * signs
    else:
        raise ValueError(f"Unknown quantization type: {quant_type}")

def quantize_4bit_linear(tensor, per_channel=False):
    """
    Linear 4-bit quantization with 16 levels (0-15).
    """
    if per_channel:
        dim = 0 if tensor.dim() > 1 else None 
        min_val = tensor.min(dim=dim, keepdim=True).values
        max_val = tensor.max(dim=dim, keepdim=True).values
        
        # Ensure we have a non-zero range for each channel
        mask = (max_val == min_val)
        max_val = torch.where(mask, min_val + 1e-6, max_val)
    else:
        min_val = tensor.min()
        max_val = tensor.max()
        
        # Ensure we have a non-zero range
        if max_val == min_val:
            max_val = min_val + 1e-6

    scale = (max_val - min_val) / 15
    zero_point = min_val

    # Quantize
    q_tensor = torch.clamp(torch.round((tensor - min_val) / scale), 0, 15).to(torch.uint8)

    return q_tensor, scale, zero_point

def quantize_4bit_nf4(tensor):
    """
    Normalized float 4-bit quantization using predefined levels.
    """
    nf4_levels = torch.tensor([
        -1.0, -0.6961928009986877, -0.5250730514526367, -0.39491748809814453,
        -0.28444138169288635, -0.18477343022823334, -0.09105003625154495, 0.0,
        0.07958029955625534, 0.16093020141124725, 0.24611230194568634, 0.33791524171829224,
        0.44070982933044434, 0.5626170039176941, 0.7229568362236023, 1.0
    ])

    abs_max = torch.max(torch.abs(tensor))
    normalized = tensor / abs_max
    expanded = normalized.unsqueeze(-1)
    distances = torch.abs(expanded - nf4_levels)
    indices = torch.argmin(distances, dim=-1)
    
    return indices.to(torch.uint8), nf4_levels, abs_max

def quantize_4bit_fp4(tensor):
    """
    Floating point 4-bit quantization.
    """
    signs = torch.sign(tensor)
    abs_values = torch.abs(tensor)

    log_values = torch.log2(abs_values + (abs_values == 0).float())
    exp_bias = 1 
    exp_values = torch.clamp(torch.round(log_values + exp_bias), 0, 3)
    mantissa_values = torch.round((abs_values / (2 ** (exp_values - exp_bias))) - 1)
    mantissa_values = torch.clamp(mantissa_values, 0, 1)

    # Convert to uint8 before bitwise operations
    exp_values = exp_values.to(torch.uint8)
    mantissa_values = mantissa_values.to(torch.uint8)
    q_tensor = ((exp_values << 1) | mantissa_values).to(torch.uint8)
    
    # Convert signs to uint8 for bitwise operation
    signs = (signs < 0).to(torch.uint8)
    q_tensor = torch.where(signs, q_tensor | 0x8, q_tensor)
    
    return q_tensor, None ,exp_bias

def quantize_8bit_fp8(tensor):
    """
    Floating point 8-bit quantization.
    """
    signs = torch.sign(tensor)
    abs_values = torch.abs(tensor)

    log_values = torch.log2(abs_values + (abs_values == 0).float())

    exp_bias = 7 
    exp_values = torch.clamp(torch.round(log_values + exp_bias), 0, 15)

    mantissa_values = torch.round((abs_values / (2 ** (exp_values - exp_bias))) * 8 - 8)
    mantissa_values = torch.clamp(mantissa_values, 0, 7)

    # Convert to uint8 before bitwise operations
    exp_values = exp_values.to(torch.uint8)
    mantissa_values = mantissa_values.to(torch.uint8)
    q_tensor = ((exp_values << 3) | mantissa_values).to(torch.uint8)
    
    # Convert signs to uint8 for bitwise operation
    signs = (signs < 0).to(torch.uint8)
    q_tensor = torch.where(signs, q_tensor | 0x80, q_tensor)
    
    return q_tensor, None,exp_bias

def quantize_8bit_nf8(tensor):
    """
    Normalized float 8-bit quantization using tanh-based levels.
    """
    nf8_levels = torch.linspace(-1, 1, 256)
    nf8_levels = torch.tanh(nf8_levels * 2)

    abs_max = torch.max(torch.abs(tensor))
    normalized = tensor / abs_max
    expanded = normalized.unsqueeze(-1)
    distances = torch.abs(expanded - nf8_levels)
    indices = torch.argmin(distances, dim=-1)
    
    return indices.to(torch.uint8), nf8_levels, abs_max

def quantize_8bit_linear(tensor, per_channel=False):
    """
    Linear 8-bit quantization with 256 levels (0-255).
    """
    if per_channel:
        dim = 0 if tensor.dim() > 1 else None
        min_val = tensor.min(dim=dim, keepdim=True).values
        max_val = tensor.max(dim=dim, keepdim=True).values
        
        # Ensure we have a non-zero range for each channel
        mask = (max_val == min_val)
        max_val = torch.where(mask, min_val + 1e-6, max_val)
    else:
        min_val = tensor.min()
        max_val = tensor.max()
        
        # Ensure we have a non-zero range
        if max_val == min_val:
            max_val = min_val + 1e-6
    
    scale = (max_val - min_val) / 255
    zero_point = min_val
    
    # Use higher precision for intermediate calculations
    q_tensor = torch.clamp(torch.round((tensor - min_val) / scale), 0, 255).to(torch.uint8)
    return q_tensor, scale, zero_point 