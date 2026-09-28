"""
Shared metric computation utilities for satellite data processing.
"""

import numpy as np
from typing import Dict, Tuple


def compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    Compute NDVI from red and NIR bands.
    
    NDVI = (NIR - RED) / (NIR + RED)
    
    Args:
        red: Red band reflectance (B04)
        nir: NIR band reflectance (B08)
    
    Returns:
        NDVI raster
    """
    denominator = nir.astype(float) + red.astype(float)
    denominator[denominator == 0] = np.nan
    ndvi = (nir.astype(float) - red.astype(float)) / denominator
    return np.clip(ndvi, -1, 1)


def compute_ndmi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """
    Compute NDMI (moisture proxy) from NIR and SWIR bands.
    
    NDMI = (NIR - SWIR) / (NIR + SWIR)
    
    Args:
        nir: NIR band reflectance (B08)
        swir: SWIR band reflectance (B11)
    
    Returns:
        NDMI raster
    """
    denominator = nir.astype(float) + swir.astype(float)
    denominator[denominator == 0] = np.nan
    ndmi = (nir.astype(float) - swir.astype(float)) / denominator
    return np.clip(ndmi, -1, 1)


def compute_ndre(nir: np.ndarray, red_edge: np.ndarray) -> np.ndarray:
    """
    Compute NDRE (chlorophyll proxy) from NIR and Red-Edge bands.
    
    NDRE = (NIR - RE) / (NIR + RE)
    
    Args:
        nir: NIR band reflectance (B08)
        red_edge: Red-Edge band reflectance (B05, B06, or B07)
    
    Returns:
        NDRE raster
    """
    denominator = nir.astype(float) + red_edge.astype(float)
    denominator[denominator == 0] = np.nan
    ndre = (nir.astype(float) - red_edge.astype(float)) / denominator
    return np.clip(ndre, -1, 1)


def compute_ci_red_edge(nir: np.ndarray, red_edge: np.ndarray) -> np.ndarray:
    """
    Compute Chlorophyll Index Red-Edge.
    
    CIre = (NIR / RE) - 1
    
    Args:
        nir: NIR band reflectance (B08)
        red_edge: Red-Edge band reflectance (B05)
    
    Returns:
        CIre raster
    """
    denominator = red_edge.astype(float)
    denominator[denominator == 0] = np.nan
    cire = (nir.astype(float) / denominator) - 1
    return cire


def compute_field_statistics(raster: np.ndarray) -> Dict[str, float]:
    """
    Compute field-level statistics from a raster.
    
    Args:
        raster: Input raster array
    
    Returns:
        Dictionary with mean, median, p10, p90, std
    """
    valid_data = raster[~np.isnan(raster)]
    
    if len(valid_data) == 0:
        return {
            'mean': np.nan,
            'median': np.nan,
            'p10': np.nan,
            'p90': np.nan,
            'std': np.nan,
            'min': np.nan,
            'max': np.nan,
            'count': 0
        }
    
    return {
        'mean': float(np.mean(valid_data)),
        'median': float(np.median(valid_data)),
        'p10': float(np.percentile(valid_data, 10)),
        'p90': float(np.percentile(valid_data, 90)),
        'std': float(np.std(valid_data)),
        'min': float(np.min(valid_data)),
        'max': float(np.max(valid_data)),
        'count': int(len(valid_data))
    }


def compute_spatial_variability_zones(
    raster: np.ndarray
) -> Dict[str, Dict[str, float]]:
    """
    Classify raster into low/medium/high vigor zones based on percentiles.
    
    Args:
        raster: Input raster array
    
    Returns:
        Dictionary with zone statistics
    """
    valid_data = raster[~np.isnan(raster)]
    
    if len(valid_data) == 0:
        return {}
    
    p33 = np.percentile(valid_data, 33)
    p66 = np.percentile(valid_data, 66)
    
    low_zone = raster < p33
    mid_zone = (raster >= p33) & (raster < p66)
    high_zone = raster >= p66
    
    total_pixels = (~np.isnan(raster)).sum()
    
    return {
        'lowZone': {
            'pixels': int(low_zone.sum()),
            'percentArea': float(low_zone.sum() / total_pixels * 100) if total_pixels > 0 else 0,
            'meanValue': float(np.mean(raster[low_zone])) if low_zone.sum() > 0 else np.nan
        },
        'midZone': {
            'pixels': int(mid_zone.sum()),
            'percentArea': float(mid_zone.sum() / total_pixels * 100) if total_pixels > 0 else 0,
            'meanValue': float(np.mean(raster[mid_zone])) if mid_zone.sum() > 0 else np.nan
        },
        'highZone': {
            'pixels': int(high_zone.sum()),
            'percentArea': float(high_zone.sum() / total_pixels * 100) if total_pixels > 0 else 0,
            'meanValue': float(np.mean(raster[high_zone])) if high_zone.sum() > 0 else np.nan
        },
        'p33': float(p33),
        'p66': float(p66)
    }


def compute_gdd(tmin: float, tmax: float, base: float = 50, cap: float = 86) -> float:
    """
    Compute Growing Degree Days (GDD) for corn.
    
    GDD = ((Tmax_capped + Tmin_capped) / 2) - base
    
    Args:
        tmin: Minimum temperature (°F)
        tmax: Maximum temperature (°F)
        base: Base temperature (default 50°F for corn)
        cap: Cap temperature (default 86°F for corn)
    
    Returns:
        GDD value
    """
    tmax_capped = min(tmax, cap)
    tmin_capped = max(tmin, base)
    gdd = ((tmax_capped + tmin_capped) / 2) - base
    return max(0, gdd)


def compute_confidence_from_age(
    days_since_observation: int,
    valid_pixel_fraction: float = 1.0
) -> Tuple[str, float]:
    """
    Determine observation confidence based on age and cloud cover.
    
    Args:
        days_since_observation: Days since last clear satellite observation
        valid_pixel_fraction: Fraction of valid (non-cloud) pixels in observation
    
    Returns:
        Tuple of (confidence_level, confidence_score)
    """
    # Quality based on valid pixels
    if valid_pixel_fraction >= 0.7:
        quality = 'high'
        quality_score = 1.0
    elif valid_pixel_fraction >= 0.4:
        quality = 'medium'
        quality_score = 0.7
    else:
        quality = 'low'
        quality_score = 0.4
    
    # Age decay
    if days_since_observation <= 5:
        age_factor = 1.0
    elif days_since_observation <= 12:
        age_factor = 0.7
    else:
        age_factor = 0.4
    
    combined_score = quality_score * age_factor
    
    if combined_score >= 0.7:
        confidence = 'high'
    elif combined_score >= 0.4:
        confidence = 'medium'
    else:
        confidence = 'low'
    
    return confidence, combined_score
