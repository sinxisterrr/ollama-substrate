#!/usr/bin/env python3
"""
Lightweight JSON importer for Substrate AI.

Drop memory JSON exports into backend/data/imports (or set DATA_IMPORT_DIR)
and they will be ingested into PostgreSQL + SQLite on startup.
"""

import json
import os
import shutil
import uuid
from typing import Any, Dict, List, Optional

from core.state_manager import StateManager, BlockType, StateManagerError
from core.postgres_manager import PostgresManager


def import_json_memories(
    state_manager: StateManager,
    postgres_manager: Optional[PostgresManager] = None,
    import_dir: str = "./data/imports"
) -> int:
    """
    Ingest memory JSON files into the agent databases.

    Args:
        state_manager: Core state manager (SQLite)
        postgres_manager: Optional PostgreSQL manager for long-term memory
        import_dir: Directory containing *.json files to import

    Returns:
        Number of memory entries imported.
    """
    resolved_dir = os.path.abspath(import_dir)
    os.makedirs(resolved_dir, exist_ok=True)

    json_files = [
        os.path.join(resolved_dir, f)
        for f in sorted(os.listdir(resolved_dir))
        if f.lower().endswith(".json")
        and os.path.isfile(os.path.join(resolved_dir, f))
    ]

    if not json_files:
        return 0

    processed_dir = os.path.join(resolved_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    agent_state = state_manager.get_agent_state()
    agent_id = agent_state.get("id", "default")

    from letta_compat.import_agent import LettaAgentImporter

    importer = LettaAgentImporter(state_manager)
    imported_entries = 0

    for file_path in json_files:
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            print(f"⚠️  Skipping {file_name}: cannot read JSON ({exc})")
            continue

        # Letta .af files are JSON with 'agents' + 'blocks'
        if isinstance(payload, dict) and "agents" in payload and "blocks" in payload:
            try:
                importer.import_from_file(file_path)
                imported_entries += 1
                print(f"✅ Imported Letta agent from {file_name}")
            except Exception as exc:
                print(f"⚠️  Failed to import {file_name}: {exc}")
                continue
        else:
            entries = _extract_entries(payload)
            if not entries:
                print(f"⚠️  No memories found in {file_name}")
            ingested = 0
            for entry in entries:
                if _store_memory_entry(entry, state_manager, postgres_manager, agent_id):
                    ingested += 1
            if ingested:
                imported_entries += ingested
                print(f"✅ Imported {ingested} memories from {file_name}")

        # Move processed file so we don't import twice
        dest_path = os.path.join(processed_dir, file_name)
        try:
            shutil.move(file_path, dest_path)
        except Exception:
            pass

    if imported_entries:
        print(f"✅ Data import complete: {imported_entries} entries ingested")
    return imported_entries


def _extract_entries(payload: Any) -> List[Dict[str, Any]]:
    """Normalize different JSON layouts into a list of dict entries."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("memories", "memory_blocks", "blocks", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]

    return []


def _store_memory_entry(
    entry: Dict[str, Any],
    state_manager: StateManager,
    postgres_manager: Optional[PostgresManager],
    agent_id: str
) -> bool:
    """Persist a single memory entry."""
    content = entry.get("content") or entry.get("value") or entry.get("text", "")
    if not content:
        return False

    label = (
        entry.get("label")
        or entry.get("name")
        or entry.get("title")
        or f"memory_{uuid.uuid4().hex[:8]}"
    )

    description = entry.get("description", "")
    read_only = bool(entry.get("read_only", False))
    metadata = entry.get("metadata") or {}
    tags = entry.get("tags") or []
    limit = int(entry.get("limit", 2000))
    hidden = bool(entry.get("hidden", False))

    block_type_value = (
        entry.get("block_type")
        or entry.get("memory_type")
        or entry.get("type")
        or "custom"
    )
    block_type = _map_block_type(block_type_value)

    try:
        existing = state_manager.get_block(label)
    except StateManagerError:
        existing = None

    try:
        if existing:
            state_manager.update_block(label, content, check_read_only=False)
        else:
            state_manager.create_block(
                label=label,
                content=content,
                block_type=block_type,
                limit=limit,
                read_only=read_only,
                description=description,
                metadata=metadata,
                hidden=hidden,
            )
    except Exception as exc:
        print(f"⚠️  Failed to store '{label}' in SQLite: {exc}")

    pg_memory_type = (entry.get("memory_type") or entry.get("type") or "core").lower()
    if pg_memory_type not in ("core", "archival", "recall"):
        pg_memory_type = "core"

    if postgres_manager:
        try:
            postgres_manager.add_memory(
                agent_id=agent_id,
                memory_type=pg_memory_type,
                label=label,
                content=content,
                tags=tags,
                metadata=metadata,
            )
        except Exception as exc:
            print(f"⚠️  Failed to store '{label}' in PostgreSQL: {exc}")
            return False

    return True


def _map_block_type(value: str) -> BlockType:
    """Map various strings to BlockType enum."""
    normalized = (value or "").lower()
    if normalized in ("persona", "identity"):
        return BlockType.PERSONA
    if normalized in ("human", "user", "relationship", "profile"):
        return BlockType.HUMAN
    return BlockType.CUSTOM
