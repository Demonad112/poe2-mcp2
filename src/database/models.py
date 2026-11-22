"""
SQLAlchemy database models for PoE2 game data
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    """Item base types and data"""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    base_type: Mapped[str] = mapped_column(String, nullable=False)
    item_class: Mapped[str] = mapped_column(String, nullable=False, index=True)
    rarity: Mapped[Optional[str]] = mapped_column(String)  # normal, magic, rare, unique
    item_level: Mapped[Optional[int]] = mapped_column(Integer)
    required_level: Mapped[Optional[int]] = mapped_column(Integer)
    properties: Mapped[Optional[Any]] = mapped_column(JSON)  # Dict of properties
    requirements: Mapped[Optional[Any]] = mapped_column(JSON)  # Stat requirements
    implicit_mods: Mapped[Optional[Any]] = mapped_column(JSON)  # List of implicit modifiers
    explicit_mods: Mapped[Optional[Any]] = mapped_column(JSON)  # List of explicit modifiers
    flavour_text: Mapped[Optional[str]] = mapped_column(Text)
    is_corrupted: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UniqueItem(Base):
    """Unique item data"""

    __tablename__ = "unique_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    base_type: Mapped[str] = mapped_column(String, nullable=False)
    item_class: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # Helmet, Body Armour, Weapon, etc.
    required_level: Mapped[Optional[int]] = mapped_column(Integer)  # Alias for level_requirement
    level_requirement: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Alternative name used by scripts
    modifiers: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # List of unique modifiers (alias for mods)
    mods: Mapped[Optional[Any]] = mapped_column(JSON)  # Alternative name for modifiers
    stats: Mapped[Optional[Any]] = mapped_column(JSON)  # Item stats including chaos_value
    flavour_text: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)  # Additional description
    drop_level: Mapped[Optional[int]] = mapped_column(Integer)
    rarity_tier: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5
    tags: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # List of tags (e.g., ["caster", "spell_damage"])
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class Modifier(Base):
    """Item and passive modifiers"""

    __tablename__ = "modifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    mod_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # prefix, suffix, implicit, explicit
    stat_text: Mapped[Optional[str]] = mapped_column(Text)
    min_value: Mapped[Optional[float]] = mapped_column(Float)
    max_value: Mapped[Optional[float]] = mapped_column(Float)
    tags: Mapped[Optional[Any]] = mapped_column(JSON)
    tier: Mapped[Optional[int]] = mapped_column(Integer)
    item_level_requirement: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class PassiveNode(Base):
    """Passive tree nodes"""

    __tablename__ = "passive_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )  # Changed from Integer - uses Id field from .datc64
    name: Mapped[Optional[str]] = mapped_column(String)
    is_keystone: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    is_notable: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    is_mastery: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    stats: Mapped[Optional[Any]] = mapped_column(JSON)  # List of stat modifiers
    reminder_text: Mapped[Optional[str]] = mapped_column(Text)
    ascendancy_name: Mapped[Optional[str]] = mapped_column(String)  # If part of ascendancy
    position_x: Mapped[Optional[float]] = mapped_column(Float)
    position_y: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class PassiveConnection(Base):
    """Connections between passive nodes"""

    __tablename__ = "passive_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_node_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("passive_nodes.node_id")
    )
    to_node_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("passive_nodes.node_id"))


class SkillGem(Base):
    """Skill gem data"""

    __tablename__ = "skill_gems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    gem_type: Mapped[Optional[str]] = mapped_column(String)  # active, support
    tags: Mapped[Optional[Any]] = mapped_column(JSON)  # List of tags
    primary_attribute: Mapped[Optional[str]] = mapped_column(String)  # str, dex, int
    required_level: Mapped[Optional[int]] = mapped_column(Integer)
    mana_cost: Mapped[Optional[int]] = mapped_column(Integer)
    spirit_cost: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Flat spirit reservation cost (if constant)
    spirit_cost_by_level: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # Spirit cost per gem level (if variable)
    base_damage: Mapped[Optional[Any]] = mapped_column(JSON)
    damage_effectiveness: Mapped[Optional[float]] = mapped_column(Float)
    crit_chance: Mapped[Optional[float]] = mapped_column(Float)
    attack_speed: Mapped[Optional[float]] = mapped_column(Float)
    quality_stats: Mapped[Optional[Any]] = mapped_column(JSON)
    per_level_stats: Mapped[Optional[Any]] = mapped_column(JSON)  # Stats at each gem level
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class SupportGem(Base):
    """Support gem data"""

    __tablename__ = "support_gems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tags: Mapped[Optional[Any]] = mapped_column(JSON)
    required_level: Mapped[Optional[int]] = mapped_column(Integer)
    mana_multiplier: Mapped[Optional[float]] = mapped_column(Float)
    spirit_cost: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Flat spirit reservation cost (if any)
    spirit_cost_by_level: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # Spirit cost per gem level (if variable)
    modifiers: Mapped[Optional[Any]] = mapped_column(JSON)  # List of modifiers
    quality_stats: Mapped[Optional[Any]] = mapped_column(JSON)
    compatible_tags: Mapped[Optional[Any]] = mapped_column(JSON)  # Which skill tags this supports
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class Ascendancy(Base):
    """Ascendancy class data"""

    __tablename__ = "ascendancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    base_class: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    notable_passives: Mapped[Optional[Any]] = mapped_column(JSON)  # List of notable passive IDs
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class SavedBuild(Base):
    """User-saved builds"""

    __tablename__ = "saved_builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String, index=True
    )  # Optional user identification
    build_name: Mapped[str] = mapped_column(String, nullable=False)
    character_data: Mapped[Optional[Any]] = mapped_column(JSON)
    optimization_history: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # List of optimization results
    notes: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[Any]] = mapped_column(JSON)
    is_public: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ItemMod(Base):
    """Item modifiers (affixes) from mods.datc64"""

    __tablename__ = "item_mods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mod_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )  # e.g., "Strength1", "IncreasedLife1"
    generation_type: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )  # 1=prefix, 2=suffix, 3=implicit, 5=corrupted
    generation_type_name: Mapped[Optional[str]] = mapped_column(
        String
    )  # "PREFIX", "SUFFIX", "IMPLICIT", "CORRUPTED"
    domain_flag: Mapped[Optional[int]] = mapped_column(Integer)  # Domain flag from .datc64
    level_requirement: Mapped[Optional[int]] = mapped_column(
        Integer, index=True
    )  # Minimum item level required
    mod_group: Mapped[Optional[str]] = mapped_column(
        String, index=True
    )  # For exclusivity checking (derived from mod_id base)
    tier: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Quality tier (derived from numeric suffix in mod_id)
    min_value: Mapped[Optional[int]] = mapped_column(Integer)  # Minimum roll value
    max_value: Mapped[Optional[int]] = mapped_column(Integer)  # Maximum roll value
    stats: Mapped[Optional[Any]] = mapped_column(
        JSON
    )  # Array of stat modifications with slot/index/value
    strings: Mapped[Optional[Any]] = mapped_column(JSON)  # String data including display names
    row_index: Mapped[Optional[int]] = mapped_column(Integer)  # Original row index in .datc64 file
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class GameDataVersion(Base):
    """Track game data version"""

    __tablename__ = "game_data_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_source: Mapped[str] = mapped_column(String, nullable=False)  # poe2db, official_api, etc.
    version: Mapped[Optional[str]] = mapped_column(String)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    data_hash: Mapped[Optional[str]] = mapped_column(String)  # Hash of data to detect changes
