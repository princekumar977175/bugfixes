"""Corridor track section routes for querying active and scheduled disruptions."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import DisruptionItem, SectionDisruptionsResponse
from src.db.models import Disruption, Section
from src.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sections", tags=["Sections"])


@router.get("/{section_id}/disruptions", response_model=SectionDisruptionsResponse)
def get_section_disruptions(
    section_id: str,
    active_only: bool = Query(False, description="Filter for disruptions active at the query timestamp"),
    timestamp: str | None = Query(None, description="ISO timestamp for active filter"),
    db: Session = Depends(get_db),
) -> SectionDisruptionsResponse:
    """Retrieve disruptions affecting a track section or all corridor sections."""
    query = select(Disruption)

    if section_id.lower() != "all":
        # Validate section exists
        sec = db.execute(select(Section).where(Section.id == section_id)).scalar_one_or_none()
        if not sec:
            raise HTTPException(status_code=404, detail=f"Corridor section '{section_id}' not found.")
        query = query.where(Disruption.section_id == section_id)

    if active_only:
        if timestamp:
            try:
                as_of = datetime.fromisoformat(timestamp)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {timestamp}") from err
        else:
            as_of = datetime.now()
        query = query.where(Disruption.start_time <= as_of, Disruption.end_time >= as_of)

    query = query.order_by(Disruption.start_time.desc())
    disruptions = db.execute(query).scalars().all()

    items = [
        DisruptionItem(
            id=d.id,
            section_id=d.section_id,
            type=d.type,
            start_time=d.start_time.isoformat(),
            end_time=d.end_time.isoformat(),
            severity=round(d.severity, 2),
        )
        for d in disruptions
    ]

    return SectionDisruptionsResponse(
        section_id=section_id,
        total=len(items),
        disruptions=items,
    )
