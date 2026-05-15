"""
知识库路由：文件上传、列表、删除、命名、共享管理
支持 .txt, .md, .docx, .pdf
"""
import logging
import os
import re
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import joinedload

from database import get_db
from models import User, KnowledgeFile, SharedKnowledge
from schemas import KnowledgeFileResponse, UpdateKnowledgeName
from auth import get_current_user, get_admin_user
from services.rag_service import index_document_rag as index_document, delete_document_chunks, get_user_collection_name

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

logger = logging.getLogger("knowledge")

ALLOWED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}
MAX_FILE_SIZE = 300 * 1024 * 1024  # 300MB


def extract_text_from_txt(content_bytes: bytes) -> str:
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return content_bytes.decode("gbk")
        except UnicodeDecodeError:
            return content_bytes.decode("utf-8", errors="ignore")


def extract_text_from_docx(content_bytes: bytes) -> str:
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph
        from docx.table import Table
        import io
        doc = Document(io.BytesIO(content_bytes))
        body = doc.element.body
        parts = []
        for child in body:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'p':
                para = Paragraph(child, doc)
                text = para.text.strip()
                if text:
                    parts.append(text)
            elif tag == 'tbl':
                table = Table(child, doc)
                if table.rows:
                    rows = table.rows
                    ncols = len(rows[0].cells)
                    grid = []
                    for ri in range(len(rows)):
                        row_cells = []
                        for cell in rows[ri].cells:
                            cell_text = cell.text.strip()
                            tcPr = cell._tc.tcPr
                            gridSpan = 1
                            if tcPr is not None:
                                gs_el = tcPr.find(qn('w:gridSpan'))
                                if gs_el is not None:
                                    gridSpan = int(gs_el.get(qn('w:val'), 1))
                            for _ in range(gridSpan):
                                row_cells.append(cell_text)
                        while len(row_cells) < ncols:
                            row_cells.append('')
                        grid.append(row_cells[:ncols])
                    md_lines = ['| ' + ' | '.join(grid[0]) + ' |']
                    md_lines.append('|' + ''.join(' --- |' for _ in range(ncols)))
                    for r in range(1, len(grid)):
                        md_lines.append('| ' + ' | '.join(grid[r]) + ' |')
                    parts.append('\n' + '\n'.join(md_lines) + '\n')
        result = '\n\n'.join(parts)
        if not result.strip():
            raise ValueError("Word document contains no extractable text")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析 Word 文件失败: {str(e)}")


def extract_text_from_pdf(content_bytes: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content_bytes))
        if len(reader.pages) == 0:
            raise ValueError("PDF file has no pages")
        text_parts = []
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    text_parts.append(page_text)
            except Exception:
                continue
        if not text_parts:
            raise ValueError("PDF pages contain no extractable text")
        return "\n".join(text_parts)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析 PDF 文件失败: {str(e)}")


def extract_text(file: UploadFile, content_bytes: bytes) -> str:
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".txt" or ext == ".md":
        return extract_text_from_txt(content_bytes)
    elif ext == ".docx":
        return extract_text_from_docx(content_bytes)
    elif ext == ".pdf":
        return extract_text_from_pdf(content_bytes)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    name: str = Query(None, description="知识库名称"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}",
        )

    logger.info(f"收到上传请求: user={current_user.email}, file={file.filename}, ext={ext}")

    content_bytes = await file.read()
    file_size = len(content_bytes)
    logger.info(f"文件读取完成: size={file_size} bytes")

    if file_size == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小超过限制(最大300MB)，当前文件大小: {file_size / (1024*1024):.2f}MB",
        )

    try:
        content = extract_text(file, content_bytes)
        logger.info(f"文本提取完成: length={len(content)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文本提取失败: {e}")
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    safe_filename = f"{current_user.id}_{file.filename}"

    try:
        chunk_count, chunks = await index_document(
            user_id=current_user.id,
            filename=safe_filename,
            content=content,
        )
    except Exception as e:
        logger.error(f"文档索引失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")

    if name:
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9\s]{2,50}$', name):
            raise HTTPException(
                status_code=400,
                detail="知识库名称只能包含中文、英文、数字和空格，长度2-50个字符",
            )
        
        result = await db.execute(
            select(KnowledgeFile)
            .where(KnowledgeFile.user_id == current_user.id)
            .where(KnowledgeFile.name == name)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="知识库名称已存在",
            )

    knowledge_file = KnowledgeFile(
        user_id=current_user.id,
        filename=safe_filename,
        original_filename=file.filename or "unknown",
        name=name,
        file_size=file_size,
        chunk_count=chunk_count,
        chroma_collection=get_user_collection_name(current_user.id),
        is_shared=False,
    )
    db.add(knowledge_file)
    await db.commit()
    await db.refresh(knowledge_file)

    logger.info(f"上传成功: file_id={knowledge_file.id}, chunks={chunk_count}")

    return {
        "id": knowledge_file.id,
        "user_id": knowledge_file.user_id,
        "filename": knowledge_file.filename,
        "original_filename": knowledge_file.original_filename,
        "name": knowledge_file.name,
        "file_size": knowledge_file.file_size,
        "chunk_count": knowledge_file.chunk_count,
        "is_shared": knowledge_file.is_shared,
        "created_at": knowledge_file.created_at,
        "chunks_preview": [
            {"index": i, "content": chunk[:200] + "..." if len(chunk) > 200 else chunk}
            for i, chunk in enumerate(chunks[:10])
        ],
        "total_chars": len(content),
    }


@router.get("/files", response_model=list[KnowledgeFileResponse])
async def list_files(
    all: bool = Query(False, description="管理员查看所有文件"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if all and current_user.is_admin:
        result = await db.execute(
            select(KnowledgeFile).order_by(KnowledgeFile.created_at.desc())
        )
    else:
        result = await db.execute(
            select(KnowledgeFile)
            .where(KnowledgeFile.user_id == current_user.id)
            .order_by(KnowledgeFile.created_at.desc())
        )
    return result.scalars().all()


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    knowledge_file = result.scalar_one_or_none()
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    if knowledge_file.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权删除该文件")

    await delete_document_chunks(
        user_id=knowledge_file.user_id,
        filename=knowledge_file.filename,
    )

    await db.delete(knowledge_file)
    await db.commit()

    return {"message": "文件已删除"}


@router.get("/files/{file_id}/chunks")
async def get_file_chunks(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    knowledge_file = result.scalar_one_or_none()
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    if knowledge_file.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    from services.rag_service import get_file_chunks

    try:
        chunks = await get_file_chunks(knowledge_file.user_id, knowledge_file.filename)
        return {"chunks": chunks, "total": len(chunks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分块失败: {str(e)}")


@router.put("/files/{file_id}/name", response_model=KnowledgeFileResponse)
async def update_knowledge_name(
    file_id: int,
    data: UpdateKnowledgeName,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    knowledge_file = result.scalar_one_or_none()
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if knowledge_file.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权修改该知识库")

    if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9\s]{2,50}$', data.name):
        raise HTTPException(
            status_code=400,
            detail="知识库名称只能包含中文、英文、数字和空格，长度2-50个字符",
        )

    result = await db.execute(
        select(KnowledgeFile)
        .where(KnowledgeFile.user_id == current_user.id)
        .where(KnowledgeFile.id != file_id)
        .where(KnowledgeFile.name == data.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="知识库名称已存在",
        )

    knowledge_file.name = data.name
    await db.commit()
    await db.refresh(knowledge_file)
    return knowledge_file


@router.put("/files/{file_id}/share")
async def toggle_share(
    file_id: int,
    is_shared: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    knowledge_file = result.scalar_one_or_none()
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if knowledge_file.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权修改该知识库")

    knowledge_file.is_shared = is_shared
    await db.commit()
    await db.refresh(knowledge_file)
    
    return {
        "message": "共享状态更新成功",
        "is_shared": knowledge_file.is_shared,
        "knowledge_id": knowledge_file.id,
    }


@router.get("/shared")
async def list_shared_knowledge(
    keyword: str = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(KnowledgeFile, User).join(
        User, KnowledgeFile.user_id == User.id
    ).where(
        KnowledgeFile.is_shared == True,
        KnowledgeFile.user_id != current_user.id,
    )
    
    if keyword:
        query = query.where(
            or_(
                KnowledgeFile.name.ilike(f"%{keyword}%"),
                KnowledgeFile.original_filename.ilike(f"%{keyword}%"),
                User.username.ilike(f"%{keyword}%"),
            )
        )
    
    query = query.order_by(KnowledgeFile.created_at.desc())
    
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = result.all()
    
    shared_files = []
    for file, user in rows:
        avatar_url = user.avatar_url.replace("\\", "/") if user.avatar_url else None
        shared_files.append({
            "id": file.id,
            "name": file.name,
            "original_filename": file.original_filename,
            "file_size": file.file_size,
            "chunk_count": file.chunk_count,
            "user_id": file.user_id,
            "username": user.username or user.email.split('@')[0],
            "avatar_url": avatar_url,
            "created_at": file.created_at,
        })
    
    total_result = await db.execute(query)
    total = len(total_result.all())
    
    return {
        "data": shared_files,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/shared/my")
async def list_my_shared_knowledge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile)
        .where(KnowledgeFile.user_id == current_user.id)
        .where(KnowledgeFile.is_shared == True)
        .order_by(KnowledgeFile.created_at.desc())
    )
    return result.scalars().all()


@router.get("/shared/addable")
async def list_addable_shared_knowledge(
    keyword: str = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SharedKnowledge.knowledge_file_id)
        .where(SharedKnowledge.user_id == current_user.id)
    )
    added_ids = {row[0] for row in result.all()}
    
    query = select(KnowledgeFile, User).join(
        User, KnowledgeFile.user_id == User.id
    ).where(
        KnowledgeFile.is_shared == True,
        KnowledgeFile.user_id != current_user.id,
        KnowledgeFile.id.not_in(added_ids),
    )
    
    if keyword:
        query = query.where(
            or_(
                KnowledgeFile.name.ilike(f"%{keyword}%"),
                KnowledgeFile.original_filename.ilike(f"%{keyword}%"),
                User.username.ilike(f"%{keyword}%"),
            )
        )
    
    query = query.order_by(KnowledgeFile.created_at.desc())
    
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = result.all()
    
    addable_files = []
    for file, user in rows:
        avatar_url = user.avatar_url.replace("\\", "/") if user.avatar_url else None
        addable_files.append({
            "id": file.id,
            "name": file.name,
            "original_filename": file.original_filename,
            "file_size": file.file_size,
            "chunk_count": file.chunk_count,
            "user_id": file.user_id,
            "username": user.username or user.email.split('@')[0],
            "avatar_url": avatar_url,
            "created_at": file.created_at,
        })
    
    total_result = await db.execute(query)
    total = len(total_result.all())
    
    return {
        "data": addable_files,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/shared/add/{knowledge_file_id}")
async def add_shared_knowledge(
    knowledge_file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.id == knowledge_file_id)
    )
    knowledge_file = result.scalar_one_or_none()
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    if not knowledge_file.is_shared:
        raise HTTPException(status_code=400, detail="该知识库未共享")
    
    if knowledge_file.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能添加自己的知识库")
    
    result = await db.execute(
        select(SharedKnowledge)
        .where(SharedKnowledge.user_id == current_user.id)
        .where(SharedKnowledge.knowledge_file_id == knowledge_file_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="已添加该知识库")
    
    shared_knowledge = SharedKnowledge(
        user_id=current_user.id,
        knowledge_file_id=knowledge_file_id,
    )
    db.add(shared_knowledge)
    await db.commit()
    
    return {"message": "添加成功"}


@router.delete("/shared/remove/{knowledge_file_id}")
async def remove_shared_knowledge(
    knowledge_file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SharedKnowledge)
        .where(SharedKnowledge.user_id == current_user.id)
        .where(SharedKnowledge.knowledge_file_id == knowledge_file_id)
    )
    shared_knowledge = result.scalar_one_or_none()
    if not shared_knowledge:
        raise HTTPException(status_code=404, detail="未找到已添加的知识库")
    
    await db.delete(shared_knowledge)
    await db.commit()
    
    return {"message": "移除成功"}


@router.get("/shared/added")
async def list_added_shared_knowledge(
    keyword: str = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(SharedKnowledge, KnowledgeFile, User)
        .join(KnowledgeFile, SharedKnowledge.knowledge_file_id == KnowledgeFile.id)
        .join(User, KnowledgeFile.user_id == User.id)
        .where(SharedKnowledge.user_id == current_user.id)
    )
    
    if keyword:
        query = query.where(
            or_(
                KnowledgeFile.name.ilike(f"%{keyword}%"),
                KnowledgeFile.original_filename.ilike(f"%{keyword}%"),
                User.username.ilike(f"%{keyword}%"),
            )
        )
    
    query = query.order_by(SharedKnowledge.created_at.desc())
    
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = result.all()
    
    added_files = []
    for shared, file, user in rows:
        shared_avatar_url = user.avatar_url.replace("\\", "/") if user.avatar_url else None
        added_files.append({
            "id": shared.id,
            "knowledge_file_id": file.id,
            "name": file.name,
            "original_filename": file.original_filename,
            "user_id": file.user_id,
            "shared_username": user.username or user.email.split('@')[0],
            "shared_avatar_url": shared_avatar_url,
            "added_at": shared.created_at,
        })
    
    total_result = await db.execute(query)
    total = len(total_result.all())
    
    return {
        "data": added_files,
        "total": total,
        "page": page,
        "page_size": page_size,
    }