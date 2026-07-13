from fastapi import APIRouter

from .auth import router as auth
from .books import router as books
from .catalog import router as catalog
from .clubs import router as clubs
from .invites import router as invites
from .users import auth_providers_router, profile_router, read_books_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth)
router.include_router(books)
router.include_router(catalog)
router.include_router(clubs)
router.include_router(invites)
router.include_router(profile_router)
router.include_router(auth_providers_router)
router.include_router(read_books_router)
