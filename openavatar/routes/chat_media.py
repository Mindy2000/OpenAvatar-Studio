"""Local conversation attachments, separate from persona-building imports."""
from __future__ import annotations
import json
import threading
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from PIL import Image
from openavatar.application import ApplicationContext
from openavatar.services.evidence import save_upload
from openavatar.services.importers import safe_filename
from openavatar.services.chat_vision import understand_image, vision_status

class LocationMessage(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default='', max_length=500)
    preview_mode: bool = False
    client_key: str = Field(min_length=1, max_length=80)

class ImageUnderstandingRequest(BaseModel):
    confirm_billable_call: bool = False
    preview_mode: bool = False

class FavoriteChange(BaseModel):
    starred: bool


def create_chat_media_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db, settings = context.db, context.settings
    vision_lock = threading.Lock()

    def row_for(avatar_id, message_id):
        context.chat.require_avatar(avatar_id)
        row = db.one('SELECT * FROM messages WHERE avatar_id=? AND id=?', (avatar_id, message_id))
        if not row:
            raise HTTPException(404, '消息不存在')
        return row

    def public(row):
        row = dict(row)
        meta = json.loads(row.get('attachment_json') or '{}')
        meta.pop('stored_name', None)
        row['attachment'] = meta
        row.pop('attachment_json', None)
        if row.get('message_kind') in {'image', 'video', 'audio', 'file'}:
            row['media_url'] = f"/api/avatars/{row['avatar_id']}/messages/{row['id']}/file"
        return row

    @router.post('/api/avatars/{avatar_id}/messages/attachment', status_code=201)
    async def attachment(avatar_id: str, request: Request, kind: str = 'file', preview_mode: bool = False,
                         duration: float = 0, client_key: str = ''):
        context.chat.require_avatar(avatar_id)
        if kind not in {'image', 'video', 'audio', 'file'} or not 0 <= duration <= 600:
            raise HTTPException(400, '附件类型或时长无效')
        if not client_key or len(client_key) > 80:
            raise HTTPException(400, '缺少发送标识')
        old = db.one('SELECT * FROM messages WHERE avatar_id=? AND client_key=?', (avatar_id, client_key))
        if old:
            return public(old)
        name = safe_filename(unquote(request.headers.get('X-File-Name', 'attachment.bin')))[:180]
        suffix = Path(name).suffix.lower()
        allowed = {'image': {'.png', '.jpg', '.jpeg', '.webp', '.gif'},
                   'video': {'.mp4', '.webm', '.mov'}, 'audio': {'.webm', '.ogg', '.mp3', '.wav', '.m4a', '.mp4'}}
        if kind in allowed and suffix not in allowed[kind]:
            raise HTTPException(415, '请选择支持的图片、视频或音频格式')
        folder = settings.avatars_dir / avatar_id / 'chat-attachments'
        stored_name = uuid.uuid4().hex + suffix
        target = folder / stored_name
        try:
            size = await save_upload(request, target, min(settings.max_upload_bytes, 50 * 1024 * 1024))
            if not size:
                raise HTTPException(400, '不能发送空文件')
            if kind == 'image':
                try:
                    with Image.open(target) as im:
                        im.verify()
                except Exception as exc:
                    raise HTTPException(415, '图片无法读取，请重新选择') from exc
            mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            if kind == 'audio' and suffix == '.webm': mime = 'audio/webm'
            if kind in {'video', 'audio'}:
                with target.open('rb') as handle:
                    signature = handle.read(32)
                if not (signature.startswith((b'\x1aE\xdf\xa3', b'OggS', b'RIFF', b'ID3', b'\xff')) or signature[4:8] == b'ftyp'):
                    raise HTTPException(415, '音视频文件格式无法识别')
            meta = {'name': name, 'size': size, 'mime': mime, 'duration': round(duration, 1), 'stored_name': stored_name}
            labels = {'image': '图片', 'video': '视频', 'audio': '语音', 'file': '文件'}
            content = f"[{labels[kind]}] {name}（附件保存在本机，尚未解读内容）"
            mid = db.execute('INSERT INTO messages(avatar_id,role,content,channel,created_at,message_kind,attachment_json,client_key,media_type) VALUES(?,?,?,?,?,?,?,?,?)',
                (avatar_id, 'user', content, 'preview' if preview_mode else 'chat', int(time.time()), kind, json.dumps(meta, ensure_ascii=False), client_key, mime))
        except Exception:
            target.unlink(missing_ok=True)
            # Concurrent retries of the same send must never create two bubbles.
            old = db.one('SELECT * FROM messages WHERE avatar_id=? AND client_key=?', (avatar_id, client_key))
            if old: return public(old)
            raise
        return public(row_for(avatar_id, mid))

    @router.get('/api/avatars/{avatar_id}/image-understanding')
    def image_understanding_status(avatar_id: str):
        context.chat.require_avatar(avatar_id)
        return vision_status(db, avatar_id)

    @router.post('/api/avatars/{avatar_id}/messages/{message_id}/understand')
    def understand(avatar_id: str, message_id: int, payload: ImageUnderstandingRequest):
        row = row_for(avatar_id, message_id)
        if row['message_kind'] != 'image' or row['role'] != 'user' or (row['channel'] == 'preview') != payload.preview_mode:
            raise HTTPException(404, '图片不在当前对话中')
        if not payload.confirm_billable_call:
            raise HTTPException(400, '读取图片会发送给所选看图服务并可能产生费用，请确认')
        if not vision_lock.acquire(blocking=False):
            raise HTTPException(409, '正在读取图片，请稍候，不要重复发送')
        try:
            return understand_image(context, row_for(avatar_id, message_id))
        finally:
            vision_lock.release()

    @router.get('/api/avatars/{avatar_id}/messages/{message_id}/file')
    def file(avatar_id: str, message_id: int, download: bool = False):
        row = row_for(avatar_id, message_id)
        meta = json.loads(row.get('attachment_json') or '{}')
        folder = (settings.avatars_dir / avatar_id / 'chat-attachments').resolve()
        target = (folder / meta.get('stored_name', '')).resolve()
        if target.parent != folder or not target.is_file():
            raise HTTPException(404, '附件不存在')
        inline = row['message_kind'] in {'image', 'video', 'audio'} and not download
        # Files such as HTML/SVG always download; never execute user files on the app origin.
        return FileResponse(target, media_type=meta.get('mime') if inline else 'application/octet-stream',
            filename=meta.get('name', 'attachment'), content_disposition_type='inline' if inline else 'attachment',
            headers={'Content-Security-Policy': "default-src 'none'; sandbox"})

    @router.post('/api/avatars/{avatar_id}/messages/location', status_code=201)
    def location(avatar_id: str, payload: LocationMessage):
        context.chat.require_avatar(avatar_id)
        old = db.one('SELECT * FROM messages WHERE avatar_id=? AND client_key=?', (avatar_id, payload.client_key))
        if old: return public(old)
        if not payload.name.strip(): raise HTTPException(400, '请填写地点名称')
        meta = {'name': payload.name.strip(), 'address': payload.address.strip()}
        mid = db.execute('INSERT INTO messages(avatar_id,role,content,channel,created_at,message_kind,attachment_json,client_key) VALUES(?,?,?,?,?,?,?,?)',
            (avatar_id, 'user', f"[位置] {meta['name']} {meta['address']}", 'preview' if payload.preview_mode else 'chat', int(time.time()), 'location', json.dumps(meta, ensure_ascii=False), payload.client_key))
        return public(row_for(avatar_id, mid))

    @router.patch('/api/avatars/{avatar_id}/messages/{message_id}/favorite')
    def favorite(avatar_id: str, message_id: int, payload: FavoriteChange):
        row_for(avatar_id, message_id)
        db.execute('UPDATE messages SET starred=? WHERE avatar_id=? AND id=?', (int(payload.starred), avatar_id, message_id))
        return {'starred': payload.starred}

    @router.get('/api/avatars/{avatar_id}/favorites')
    def favorites(avatar_id: str):
        context.chat.require_avatar(avatar_id)
        return [public(row) for row in db.all('SELECT * FROM messages WHERE avatar_id=? AND starred=1 ORDER BY id DESC LIMIT 200', (avatar_id,))]

    @router.post('/api/avatars/{avatar_id}/messages/{message_id}/resend', status_code=201)
    def resend(avatar_id: str, message_id: int, payload: LocationMessage):
        # Reuse a reference to the same locally stored attachment, without duplicating bytes.
        row = row_for(avatar_id, message_id)
        old = db.one('SELECT * FROM messages WHERE avatar_id=? AND client_key=?', (avatar_id, payload.client_key))
        if old: return public(old)
        mid = db.execute('INSERT INTO messages(avatar_id,role,content,channel,created_at,message_kind,attachment_json,client_key,media_type) VALUES(?,?,?,?,?,?,?,?,?)',
            (avatar_id, 'user', row['content'], 'preview' if payload.preview_mode else 'chat', int(time.time()), row['message_kind'], row['attachment_json'], payload.client_key, row['media_type']))
        return public(row_for(avatar_id, mid))
    return router
