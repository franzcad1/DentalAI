from typing_extensions import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db.session import get_db
from app.models.orm import Location
from app.models.schemas import LocationRead, NexHealthResponse, PaginatedList

router = APIRouter(prefix="/locations", tags=["locations"])

Auth = Annotated[dict, Depends(require_auth)]
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NexHealthResponse[PaginatedList[LocationRead]])
def list_locations(_: Auth, db: DB) -> NexHealthResponse[PaginatedList[LocationRead]]:
    locations = db.query(Location).order_by(Location.name).all()
    return NexHealthResponse(data=PaginatedList(items=locations, total=len(locations)))
