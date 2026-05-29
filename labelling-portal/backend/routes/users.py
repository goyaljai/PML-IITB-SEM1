from fastapi import APIRouter, Depends
from auth import get_current_user

router = APIRouter()


@router.get("/me")
def me(user=Depends(get_current_user)):
    return user


@router.get("/login")
def login(user=Depends(get_current_user)):
    return user
