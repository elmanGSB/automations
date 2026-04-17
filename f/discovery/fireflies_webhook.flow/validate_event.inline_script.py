import wmill

def main(eventType: str = "", meetingId: str = "", **kwargs) -> dict:
    """Accept Fireflies native fields. Return skip=True for non-transcription events."""
    if eventType not in ("Transcription complete", "meeting.transcribed"):
        # Graceful skip — test pings, other events
        return {"skip": True, "reason": f"ignored: {eventType!r}", "event": "", "meeting_id": ""}
    if not meetingId:
        return {"skip": True, "reason": "missing meetingId", "event": "", "meeting_id": ""}
    return {"skip": False, "reason": "", "event": eventType, "meeting_id": meetingId}