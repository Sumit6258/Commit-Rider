"""Terrain: map daily contribution counts to a smooth, loopable height profile."""

from commit_rider.terrain.generator import TerrainParams, generate_terrain
from commit_rider.terrain.geometry import Terrain

__all__ = ["Terrain", "TerrainParams", "generate_terrain"]
