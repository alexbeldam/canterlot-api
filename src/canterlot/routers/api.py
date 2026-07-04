from fastapi import APIRouter

from .auth import router as auth
from .books import router as books
from .catalog import router as catalog
from .clubs import router as clubs
from .invites import router as invites

router = APIRouter(prefix="/api/v1")

router.include_router(auth)
router.include_router(books)
router.include_router(catalog)
router.include_router(clubs)
router.include_router(invites)
