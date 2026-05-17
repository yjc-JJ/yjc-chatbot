from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.emotion_service import analyze_message_emotion

router = APIRouter(prefix="/api/emotion", tags=["emotion"])

class EmotionRequest(BaseModel):
    message: str

class EmotionResponse(BaseModel):
    success: bool
    emotion: str
    confidence: float
    message: str

@router.post("/analyze", response_model=EmotionResponse)
async def analyze_emotion(request: EmotionRequest):
    """
    分析用户消息的情绪
    
    Args:
        request: 包含消息文本的请求体
        
    Returns:
        情绪分析结果
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    try:
        result = await analyze_message_emotion(request.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"情绪分析失败: {str(e)}")