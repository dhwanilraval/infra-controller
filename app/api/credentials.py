from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.machine import BMCCredential
from app.schemas.machine import BMCCredentialCreate

router = APIRouter(
    prefix="/api/v1/credentials",
    tags=["credentials"],
    dependencies=[Depends(get_current_user)],
)


@router.get("")
async def list_credentials(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BMCCredential))
    creds = result.scalars().all()
    return [
        {
            "id": c.id,
            "label": c.label,
            "username": c.username,
            "is_default": c.is_default,
        }
        for c in creds
    ]


@router.post("", status_code=201)
async def create_credential(
    data: BMCCredentialCreate, db: AsyncSession = Depends(get_db)
):
    if data.is_default:
        existing = await db.execute(
            select(BMCCredential).where(BMCCredential.is_default.is_(True))
        )
        for cred in existing.scalars():
            cred.is_default = False

    cred = BMCCredential(**data.model_dump())
    db.add(cred)
    await db.commit()
    return {"id": cred.id, "label": cred.label}


@router.delete("/{cred_id}", status_code=204)
async def delete_credential(cred_id: int, db: AsyncSession = Depends(get_db)):
    cred = await db.get(BMCCredential, cred_id)
    if not cred:
        raise HTTPException(404, "Credential not found")
    await db.delete(cred)
    await db.commit()
