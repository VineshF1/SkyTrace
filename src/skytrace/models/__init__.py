"""Data models for the Satellite Tracker application."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CoordinateSystem(str, Enum):
    GEODETIC = "geodetic"
    ECEF = "ecef"
    TOPOCENTRIC = "topocentric"


class SatellitePosition(BaseModel):
    norad_id: int
    timestamp: datetime
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_km: float = Field(..., ge=0)
    velocity_km_s: Optional[float] = Field(None, ge=0)
    coordinate_system: CoordinateSystem = Field(default=CoordinateSystem.GEODETIC)


class TopocentricPosition(BaseModel):
    norad_id: int
    timestamp: datetime
    azimuth_deg: float = Field(..., ge=0, lt=360)
    elevation_deg: float = Field(..., ge=-90, le=90)
    range_km: float = Field(..., ge=0)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_km: float = Field(..., ge=0)


class VisualPass(BaseModel):
    norad_id: int
    satellite_name: str
    rise_time: datetime
    rise_azimuth: float = Field(..., ge=0, lt=360)
    culminate_time: datetime
    culminate_elevation: float = Field(..., ge=0, le=90)
    culminate_azimuth: float = Field(..., ge=0, lt=360)
    set_time: datetime
    set_azimuth: float = Field(..., ge=0, lt=360)
    duration_seconds: float = Field(..., ge=0)
    max_magnitude: Optional[float] = None
    observer_lat: float = Field(..., ge=-90, le=90)
    observer_lon: float = Field(..., ge=-180, le=180)
    observer_alt_km: float = Field(..., ge=0)


class TLEData(BaseModel):
    norad_id: int
    name: str
    line1: str = Field(..., min_length=69, max_length=69)
    line2: str = Field(..., min_length=69, max_length=69)
    epoch: datetime
    classification: str = "U"
    international_designator: str
    element_set_no: int
    checksum1: int
    checksum2: int


class OMMSatelliteData(BaseModel):
    """Orbit Mean-Elements Message (OMM) / JSON format satellite data.
    
    OMM is the modern replacement for TLE format with no 5-digit NORAD ID limit.
    """
    norad_id: int
    name: str
    epoch: datetime
    mean_motion: float
    eccentricity: float = Field(..., ge=0, lt=1)
    inclination: float = Field(..., ge=0, le=180)
    raan: float = Field(..., ge=0, lt=360)
    arg_perigee: float = Field(..., ge=0, lt=360)
    mean_anomaly: float = Field(..., ge=0, lt=360)
    bstar: float
    semi_major_axis: Optional[float] = None
    period: Optional[float] = None


class GeocodeResult(BaseModel):
    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    country: Optional[str] = None
    admin1: Optional[str] = None
    admin2: Optional[str] = None


class UserRequest(BaseModel):
    original_text: str
    intent: str
    satellite_name: Optional[str] = None
    norad_id: Optional[int] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_km: float = 0.0
    days_ahead: int = 7


class AgentResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)