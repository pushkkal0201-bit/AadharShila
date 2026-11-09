"""Development authentication with signed HttpOnly sessions and cookie CSRF protection."""
import os, secrets, hashlib, hmac
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from .db import get_db
from .models import User

SECRET=os.getenv('SESSION_SECRET','development-only-secret-change-before-deploy')
if os.getenv('APP_ENV','development')=='production':
    forbidden={'development-only-secret-change-before-deploy','change-this-long-random-development-secret'}
    if SECRET in forbidden or len(SECRET)<32:
        raise RuntimeError('Configure a unique SESSION_SECRET of at least 32 characters in production')
    if os.getenv('SEED_DEMO','false').lower()=='true':
        raise RuntimeError('SEED_DEMO must be false in production')

def hash_password(password):
    salt=secrets.token_bytes(16)
    value=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,320000)
    return f'pbkdf2_sha256$320000${salt.hex()}${value.hex()}'
def verify_password(password,stored):
    try:
        typ,it,salt,expected=stored.split('$')
        if typ!='pbkdf2_sha256':return False
        result=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(it))
        return hmac.compare_digest(result,bytes.fromhex(expected))
    except Exception: return False

def token_for(user):
    return jwt.encode({'sub':user.id,'iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(hours=8)},SECRET,algorithm='HS256')

def current_user(request:Request,db:Session=Depends(get_db)):
    bearer=request.headers.get('authorization','')
    token=bearer[7:] if bearer.lower().startswith('bearer ') else request.cookies.get('aadharshila_session')
    if not token:raise HTTPException(status_code=401,detail='Authentication required')
    try: data=jwt.decode(token,SECRET,algorithms=['HS256'])
    except jwt.PyJWTError:raise HTTPException(status_code=401,detail='Invalid or expired session')
    user=db.get(User,data.get('sub'))
    if not user or not user.active:raise HTTPException(status_code=401,detail='Invalid account')
    if not bearer and request.method in ('POST','PATCH','PUT','DELETE'):
        csrf=request.cookies.get('aadharshila_csrf')
        if not csrf or not hmac.compare_digest(csrf,request.headers.get('X-CSRF-Token','')):
            raise HTTPException(status_code=403,detail='CSRF token missing')
    return user

def require(user,roles):
    if user.role not in roles:raise HTTPException(status_code=403,detail='Insufficient permissions')
