import shutil
import uuid
import uvicorn
import os
from fastapi import FastAPI, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, Response, FileResponse
from pydantic import BaseModel
from pexeles import (
    create_video_from_audio,
    AUDIO_FORMATS,
    Status,
    get_status,
    get_videos_zippath,
    cleanup_event,
)


app = FastAPI()


class AudioProccesing(BaseModel):
    event_id: str
    audio_description: str


@app.get("/")
def index():
    with open("index.html", "r") as htm:
        data = htm.read()
    return HTMLResponse(data)


@app.get("/download/{event_id}")
def download_zip(event_id: str, response: Response, worker: BackgroundTasks):
    zippath = get_videos_zippath(event_id)
    if zippath is None:
        response.status_code = 500
        return

    worker.add_task(cleanup_event, event_id)

    return FileResponse(zippath)


@app.get("/status/{event_id}")
def get_processing_status(event_id: str, response: Response):
    status = get_status(event_id)

    if status in [
        Status.AUDIO_LOST,
        Status.FAILED_GETTING_AUDIO_DURATION,
        Status.FAILED_TO_CREATE_VIDEO,
    ]:
        response.status_code = 500
        return {"status": status}

    if status == Status.PROCESSING_COMPLETE:
        response.status_code = 200
        return {"status": status}

    response.status_code = 202
    return {"status": status}


@app.post("/process")
def process_audio(data: AudioProccesing, worker: BackgroundTasks):
    worker.add_task(create_video_from_audio, data.event_id, data.audio_description)


@app.post("/upload-audio")
def upload_audio(audio_file: UploadFile, response: Response):
    try:
        audio_format = None
        for afmt in AUDIO_FORMATS:
            if audio_file.filename.endswith(afmt):
                audio_format = afmt
                break

        if audio_format is None:
            response.status_code = 400
            return {"eventId": None}

        event_id = str(uuid.uuid4())
        save_path = f"./vids/{event_id}"

        if not os.path.exists(save_path):
            os.makedirs(save_path)

        filepath = f"{save_path}/raw{audio_format}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)
    finally:
        audio_file.file.close()

    response.status_code = 200
    return {"eventId": event_id}


if __name__ == "__main__":
    uvicorn.run(app="main:app", host="0.0.0.0", port=3000, reload=True, workers=1)
