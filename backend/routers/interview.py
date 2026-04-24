import asyncio
import io
import json
import os
import re
import uuid
import wave
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from groq import AsyncGroq
from pydantic import BaseModel
from supabase import Client, create_client

router = APIRouter()

MIN_AUDIO_BYTES = 20000  # ~625 ms of 16-bit 16 kHz mono PCM — skip noise bursts shorter than this

def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


MAYA_GENERIC_PROMPT = (
    "You are Maya, a warm and professional AI recruiter for Reach-er. "
    "Screen candidates efficiently and fairly. Be conversational, "
    "concise, and human. Never sound robotic. Ask one question at a time."
)


def _supabase() -> Optional[Client]:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    return create_client(url, key) if url and key else None


# ── Request models ────────────────────────────────────────────────────────────

class CreateInterviewBody(BaseModel):
    job_id: Optional[str] = None
    candidate_name: str
    candidate_email: Optional[str] = None
    candidate_phone: Optional[str] = None


class CreateJobBody(BaseModel):
    title: str
    description: Optional[str] = None
    agency_id: Optional[str] = None
    required_skills: List[str] = []
    screening_questions: List[dict] = []
    interviewer_tone: str = "professional"


class UpdateJobBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[List[str]] = None
    screening_questions: Optional[List[dict]] = None
    interviewer_tone: Optional[str] = None


# ── REST endpoints ────────────────────────────────────────────────────────────

# ·· Jobs ·····································································

@router.get("/jobs")
async def list_jobs():
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        jobs_res = sb.table("jobs").select("*, agencies(name)").order("created_at", desc=True).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        interviews_res = sb.table("interviews").select("id, job_id").execute()
    except Exception:
        interviews_res = type("R", (), {"data": []})()

    counts: dict = {}
    for iv in (interviews_res.data or []):
        jid = iv.get("job_id")
        if jid:
            counts[jid] = counts.get(jid, 0) + 1

    rows = []
    for job in jobs_res.data:
        agency = job.get("agencies") or {}
        if isinstance(agency, list):
            agency = agency[0] if agency else {}
        rows.append({
            "id": job["id"],
            "title": job.get("title", ""),
            "description": job.get("description"),
            "required_skills": job.get("required_skills") or [],
            "interviewer_tone": job.get("interviewer_tone", "professional"),
            "agency_id": job.get("agency_id"),
            "agency_name": agency.get("name"),
            "interview_count": counts.get(job["id"], 0),
            "created_at": job.get("created_at"),
        })
    return rows


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        job_res = sb.table("jobs").select("*, agencies(name)").eq("id", job_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")

    job = job_res.data[0]
    agency = job.pop("agencies", None) or {}
    if isinstance(agency, list):
        agency = agency[0] if agency else {}

    try:
        iv_res = (
            sb.table("interviews")
            .select("id, status, scorecard, created_at, candidates(name, email, phone)")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        iv_res = type("R", (), {"data": []})()

    interviews = []
    for iv in (iv_res.data or []):
        scorecard = iv.get("scorecard") or {}
        candidate = iv.get("candidates") or {}
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else {}
        interviews.append({
            "id": iv["id"],
            "candidate_name": candidate.get("name", "Unknown"),
            "candidate_email": candidate.get("email"),
            "status": iv.get("status", "pending"),
            "overall_score": scorecard.get("overall_score"),
            "hire_recommendation": scorecard.get("hire_recommendation"),
            "created_at": iv.get("created_at"),
        })

    return {
        **job,
        "agency_name": agency.get("name"),
        "interviews": interviews,
    }


@router.patch("/jobs/{job_id}")
async def update_job(job_id: str, body: UpdateJobBody):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    data: dict = {}
    if body.title is not None:
        data["title"] = body.title
    if body.description is not None:
        data["description"] = body.description
    if body.required_skills is not None:
        data["required_skills"] = body.required_skills
    if body.screening_questions is not None:
        data["screening_questions"] = body.screening_questions
    if body.interviewer_tone is not None:
        data["interviewer_tone"] = body.interviewer_tone

    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        result = sb.table("jobs").update(data).eq("id", job_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    return result.data[0]


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    try:
        sb.table("jobs").delete().eq("id", job_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True}


@router.post("/jobs")
async def create_job(body: CreateJobBody):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    data: dict = {
        "title": body.title,
        "required_skills": body.required_skills,
        "screening_questions": body.screening_questions,
        "interviewer_tone": body.interviewer_tone,
    }
    if body.description:
        data["description"] = body.description
    if body.agency_id:
        data["agency_id"] = body.agency_id

    try:
        result = sb.table("jobs").insert(data).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result.data[0]

@router.post("/interviews")
async def create_interview(body: CreateInterviewBody):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    candidate_data: dict = {"name": body.candidate_name}
    if body.candidate_email:
        candidate_data["email"] = body.candidate_email
    if body.candidate_phone:
        candidate_data["phone"] = body.candidate_phone

    try:
        cand = sb.table("candidates").insert(candidate_data).execute()
        candidate_id = cand.data[0]["id"]

        interview_data: dict = {
            "candidate_id": candidate_id,
            "status": "pending",
            "transcript": [],
            "scorecard": {},
            "interviewer_name": "Maya",
        }
        if body.job_id:
            interview_data["job_id"] = body.job_id

        interview = sb.table("interviews").insert(interview_data).execute()
        interview_id = interview.data[0]["id"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "interview_id": interview_id,
        "token": str(uuid.uuid4()),
        "candidate_id": candidate_id,
    }


@router.get("/interviews")
async def list_interviews():
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        result = (
            sb.table("interviews")
            .select("id, status, scorecard, created_at, candidates(name, email, phone), jobs(title)")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    rows = []
    for iv in result.data:
        scorecard = iv.get("scorecard") or {}
        candidate = iv.get("candidates") or {}
        # PostgREST returns an array for some FK shapes — normalise
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else {}
        job = iv.get("jobs") or {}
        if isinstance(job, list):
            job = job[0] if job else {}
        rows.append({
            "id": iv["id"],
            "candidate_name": candidate.get("name", "Unknown"),
            "candidate_email": candidate.get("email"),
            "candidate_phone": candidate.get("phone"),
            "job_title": job.get("title"),
            "status": iv.get("status", "pending"),
            "overall_score": scorecard.get("overall_score"),
            "hire_recommendation": scorecard.get("hire_recommendation"),
            "created_at": iv.get("created_at"),
        })
    return rows


@router.get("/interviews/{interview_id}")
async def get_interview(interview_id: str):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")
    try:
        result = (
            sb.table("interviews")
            .select("*, candidates(name, email, phone), jobs(title, description, required_skills)")
            .eq("id", interview_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    iv = result.data[0]
    candidate = iv.pop("candidates", None) or {}
    if isinstance(candidate, list):
        candidate = candidate[0] if candidate else {}
    job = iv.pop("jobs", None) or {}
    if isinstance(job, list):
        job = job[0] if job else {}

    return {**iv, "candidate": candidate, "job": job}


@router.post("/interviews/{interview_id}/end")
async def end_interview(interview_id: str):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    try:
        result = (
            sb.table("interviews")
            .update({"status": "completed"})
            .eq("id", interview_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    row = result.data[0]
    return {"status": "completed", "transcript": row.get("transcript", [])}


# ── Scoring ───────────────────────────────────────────────────────────────────

SCORE_PROMPT_TEMPLATE = """\
You are Reach-er's evaluation engine. Analyze this interview transcript \
and score the candidate. Return ONLY valid JSON, no other text.

Job: {job_title}
Required skills: {required_skills}

Transcript:
{transcript}

Return this exact JSON structure:
{{
  "overall_score": <1-10>,
  "hire_recommendation": <true/false>,
  "summary": "<2-3 sentence summary>",
  "dimensions": [
    {{"dimension": "communication", "score": <1-10>, "reasoning": "..."}},
    {{"dimension": "relevance", "score": <1-10>, "reasoning": "..."}},
    {{"dimension": "experience", "score": <1-10>, "reasoning": "..."}},
    {{"dimension": "availability", "score": <1-10>, "reasoning": "..."}},
    {{"dimension": "culture_fit", "score": <1-10>, "reasoning": "..."}}
  ]
}}\
"""


def _format_transcript(transcript: list) -> str:
    if not transcript:
        return "(no transcript available)"
    lines = []
    for turn in transcript:
        speaker = turn.get("speaker", "unknown").capitalize()
        text = turn.get("text", "")
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


async def _run_scoring(interview_id: str, overwrite: bool = False) -> dict:
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Database not connected")

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not configured")

    # ── 1. Fetch interview ────────────────────────────────────────────────────
    try:
        iv_row = sb.table("interviews").select("*").eq("id", interview_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not iv_row.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview = iv_row.data[0]
    transcript = interview.get("transcript") or []
    job_id = interview.get("job_id")

    # ── 2. Fetch job (or fall back to generic criteria) ───────────────────────
    job_title = "General Position"
    required_skills: List[str] = []

    if job_id:
        try:
            job_row = sb.table("jobs").select("title,description,required_skills").eq("id", job_id).execute()
            if job_row.data:
                job = job_row.data[0]
                job_title = job.get("title") or job_title
                required_skills = job.get("required_skills") or []
        except Exception:
            pass  # fall through to generic criteria

    skills_str = ", ".join(required_skills) if required_skills else "general professional skills"

    # ── 3. Ask Groq to score ──────────────────────────────────────────────────
    prompt = SCORE_PROMPT_TEMPLATE.format(
        job_title=job_title,
        required_skills=skills_str,
        transcript=_format_transcript(transcript),
    )

    groq = AsyncGroq(api_key=groq_key)
    try:
        completion = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = completion.choices[0].message.content or ""
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq error: {e}")

    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        scorecard = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Groq returned invalid JSON: {e}\n\n{raw}")

    overall_score = scorecard.get("overall_score")
    hire_rec = scorecard.get("hire_recommendation")
    summary = scorecard.get("summary", "")
    dimensions = scorecard.get("dimensions", [])

    # ── 4. Persist to scores table ────────────────────────────────────────────
    try:
        if overwrite:
            sb.table("scores").delete().eq("interview_id", interview_id).execute()

        rows = [
            {
                "interview_id": interview_id,
                "dimension": dim.get("dimension", "unknown"),
                "score": dim.get("score"),
                "reasoning": dim.get("reasoning", ""),
                "overall_score": overall_score,
                "hire_recommendation": hire_rec,
                "summary": summary,
            }
            for dim in dimensions
        ]
        if rows:
            sb.table("scores").insert(rows).execute()

        # ── 5. Update interviews.scorecard ────────────────────────────────────
        sb.table("interviews").update({"scorecard": scorecard}).eq("id", interview_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database write failed: {e}")

    return scorecard


@router.post("/interviews/{interview_id}/score")
async def score_interview(interview_id: str):
    return await _run_scoring(interview_id, overwrite=False)


@router.post("/interviews/{interview_id}/score/regenerate")
async def regenerate_score(interview_id: str):
    return await _run_scoring(interview_id, overwrite=True)


# ── WebSocket pipeline ────────────────────────────────────────────────────────

@router.websocket("/ws/interview/{interview_id}")
async def interview_ws(websocket: WebSocket, interview_id: str):
    await websocket.accept()

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        await websocket.send_json({"type": "error", "text": "GROQ_API_KEY not configured"})
        await websocket.close()
        return

    groq = AsyncGroq(api_key=groq_key)
    sb = _supabase()

    # ── Build dynamic system prompt from job ──────────────────────────────────

    system_prompt = MAYA_GENERIC_PROMPT
    conversation: List[dict] = []

    if sb:
        try:
            iv_row = (
                sb.table("interviews")
                .select("job_id, transcript")
                .eq("id", interview_id)
                .execute()
            )
            if iv_row.data:
                iv = iv_row.data[0]

                # Seed conversation memory with any existing transcript turns
                for turn in (iv.get("transcript") or []):
                    role = "user" if turn.get("speaker") == "candidate" else "assistant"
                    if turn.get("text"):
                        conversation.append({"role": role, "content": turn["text"]})

                job_id = iv.get("job_id")
                if job_id:
                    job_row = (
                        sb.table("jobs")
                        .select("title, description, required_skills, screening_questions")
                        .eq("id", job_id)
                        .execute()
                    )
                    if job_row.data:
                        job = job_row.data[0]
                        job_title = job.get("title") or "this role"
                        job_description = job.get("description") or ""
                        required_skills: List[str] = job.get("required_skills") or []
                        skills_str = ", ".join(required_skills) if required_skills else "relevant skills"

                        system_prompt = f"""\
You are Maya, a warm and professional AI recruiter for Reachr \
conducting a screening interview for the following role:

Role: {job_title}
Company context: {job_description}
Required skills: {skills_str}

Your goal is to screen this candidate for this specific role.

Follow this structure:
1. Greet them warmly, introduce yourself and mention the role \
and company context briefly
2. Ask about their background relevant to {job_title}
3. For each required skill ({skills_str}), ask ONE \
focused question and dig deeper based on their answer
4. Ask about their experience with specific technologies mentioned
5. Ask a situational or problem-solving question relevant to the role
6. Close warmly — tell them next steps

Rules:
- Ask ONE question at a time, never stack multiple questions
- Listen to their answer and build your NEXT question based on it
- Be conversational, not robotic
- Reference the actual role and skills in your questions
- If they mention something interesting, follow up on it before moving on
"""
        except Exception:
            pass  # fall through to generic prompt

    # ── helpers ───────────────────────────────────────────────────────────────

    async def transcribe(pcm_bytes: bytes) -> str:
        wav = _pcm_to_wav(pcm_bytes)
        try:
            result = await groq.audio.transcriptions.create(
                file=("audio.wav", wav, "audio/wav"),
                model="whisper-large-v3",
                language="en",
                response_format="text",
            )
            text = re.sub(r'<\|[^>]+\|>', '', result or '').strip()
            print(f"Transcribed: {text}")
            return text
        except Exception as e:
            print(f"Transcription error: {e}")
            return ""

    async def get_maya_response(candidate_text: str) -> str:
        conversation.append({"role": "user", "content": candidate_text})
        messages = [{"role": "system", "content": system_prompt}, *conversation]

        full_response = ""
        try:
            stream = await groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                stream=True,
                max_tokens=512,
            )
            async for chunk in stream:
                full_response += chunk.choices[0].delta.content or ""
        except Exception:
            full_response = "I'm sorry, I had trouble processing that. Could you repeat?"

        if full_response:
            conversation.append({"role": "assistant", "content": full_response})
        return full_response

    async def persist_turn(speaker: str, text: str) -> None:
        if not sb or not text.strip():
            return
        try:
            row = sb.table("interviews").select("transcript").eq("id", interview_id).execute()
            if not row.data:
                return
            existing: list = row.data[0].get("transcript") or []
            existing.append({
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            sb.table("interviews").update({"transcript": existing}).eq("id", interview_id).execute()
        except Exception:
            pass  # never crash the pipeline over a DB write

    async def handle_turn(audio_buffer: bytearray) -> None:
        if len(audio_buffer) < MIN_AUDIO_BYTES:
            return

        transcript = await transcribe(bytes(audio_buffer))
        if not transcript:
            return

        try:
            await websocket.send_json({
                "type": "transcript",
                "text": transcript,
                "speaker": "candidate",
            })
        except Exception:
            return

        asyncio.create_task(persist_turn("candidate", transcript))

        maya_text = await get_maya_response(transcript)
        if not maya_text:
            return

        try:
            await websocket.send_json({
                "type": "transcript",
                "text": maya_text,
                "speaker": "maya",
            })
        except Exception:
            return

        asyncio.create_task(persist_turn("maya", maya_text))

    # ── main receive loop ─────────────────────────────────────────────────────

    audio_buffer = bytearray()

    try:
        while True:
            message = await websocket.receive()

            msg_type = message.get("type")

            if msg_type == "websocket.disconnect":
                break

            if msg_type != "websocket.receive":
                continue

            raw_bytes = message.get("bytes")
            raw_text = message.get("text")

            if raw_bytes:
                audio_buffer.extend(raw_bytes)
                continue

            if raw_text:
                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "clear_buffer":
                    # Maya is about to speak — discard any audio the mic picked
                    # up before or during her response to prevent echo transcription.
                    audio_buffer = bytearray()

                elif data.get("type") == "end_turn" and audio_buffer:
                    buf, audio_buffer = audio_buffer, bytearray()
                    await handle_turn(buf)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass
    finally:
        # Flush any remaining audio on disconnect
        if audio_buffer:
            try:
                await handle_turn(audio_buffer)
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
