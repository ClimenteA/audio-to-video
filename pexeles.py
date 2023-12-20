import os
import re
import shutil
import zipfile
import requests
import subprocess
from enum import StrEnum


if not os.path.exists("vids"):
    os.makedirs("vids")


PEXELES_URL = "https://api.pexels.com/videos/search"

with open("apikey.txt", "r") as f:
    PEXELES_APIKEY = f.read().strip()


AUDIO_FORMATS = [
    ".flac",
    ".mp3",
    ".wav",
    ".ogg",
    ".wma",
]


def get_duration_in_seconds(filepath: str):
    if filepath.endswith(tuple(AUDIO_FORMATS)):
        output_wav_file = os.path.join(os.path.dirname(filepath), "raw_audio.wav")
        output_wav_file_no_silence = os.path.join(
            os.path.dirname(filepath), "audio.wav"
        )
        if not os.path.exists(output_wav_file):
            ffmpeg_convert_to_wav = (
                f"ffmpeg -i {filepath} -acodec pcm_s16le -ar 44100 {output_wav_file}"
            )
            subprocess.call(ffmpeg_convert_to_wav, shell=True)

            ffmpeg_remove_silence = f"ffmpeg -i {output_wav_file} -af silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-40dB {output_wav_file_no_silence}"
            subprocess.call(ffmpeg_remove_silence, shell=True)
            filepath = output_wav_file_no_silence

    ffprobe_command = f'ffprobe -i {filepath} -show_entries format=duration -v quiet -of csv="p=0" | rev | cut -c 5- | rev'

    process = subprocess.Popen(
        ffprobe_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output, error = process.communicate()

    if error:
        print("Failed to get duration: " + error.decode())
        return 0

    duration_seconds = round(float(output.decode().strip())) + 1
    print(f"Audio/Video has {duration_seconds} seconds")
    return duration_seconds


def get_video_for_query(query: str, save_path: str):
    """
    filepath = get_video_for_query(query="lady in red", save_path=SAVE_PATH)
    """
    params = {"query": query, "per_page": 1}

    r = requests.get(
        PEXELES_URL, params=params, headers={"Authorization": PEXELES_APIKEY}
    )
    resp = r.json()

    vidinfo = None
    for vidmeta in resp["videos"]:
        for vidfilemeta in vidmeta["video_files"]:
            if (
                vidfilemeta["width"] == 1920
                and vidfilemeta["height"] == 1080
                and vidfilemeta["file_type"] == "video/mp4"
            ):
                vidinfo = vidfilemeta
                break

    if vidinfo is None:
        return

    if not os.path.exists(save_path):
        os.makedirs(save_path)

    filepath = os.path.join(save_path, f"{vidinfo['id']}.mp4")
    if os.path.exists(filepath):
        return filepath

    with open(filepath, "wb") as vid:
        response = requests.get(vidinfo["link"])
        vid.write(response.content)

    return filepath


def reencode_video(input_path, output_path):
    cmd = f"ffmpeg -i '{input_path}' -c:v libx264 -crf 23 -r 24 -c:a aac -strict experimental '{output_path}'"
    subprocess.call(cmd, shell=True)


def merge_videos(video_paths: list[str], audio_duration: int):
    save_path = os.path.dirname(video_paths[0])
    txt_path = os.path.join(save_path, "videos_to_concat.txt")
    output_path = os.path.join(save_path, "concatenated_vids.mp4")

    vidseconds = 0
    reencoded_paths = []
    for i, video_path in enumerate(video_paths):
        reencoded_path = os.path.join(save_path, f"reencoded_video_{i}.mp4")
        reencode_video(video_path, reencoded_path)
        sec = get_duration_in_seconds(reencoded_path)
        vidseconds += sec
        reencoded_paths.append(reencoded_path)

    if vidseconds < audio_duration:
        while vidseconds < audio_duration:
            reencoded_paths += reencoded_paths
            vidseconds *= vidseconds

    with open(txt_path, "w") as file:
        for path in reencoded_paths:
            file.write(f"file {os.path.basename(path)}\n")

    cmd = f"ffmpeg -f concat -safe 0 -i '{txt_path}' -c copy '{output_path}'"
    subprocess.call(cmd, shell=True)

    return output_path


def add_audio_to_video(video_path: str):
    audio_path = os.path.join(os.path.dirname(video_path), "audio.wav")
    output_path = os.path.join(os.path.dirname(video_path), "VIDEO_HD.mp4")

    cmd = f"ffmpeg -i '{video_path}' -i '{audio_path}' -c:v copy -map 0:v -map 1:a -c:a aac -strict experimental -shortest '{output_path}'"
    subprocess.call(cmd, shell=True)

    return output_path


def create_shorts_video(input_video: str):
    output_video = os.path.join(os.path.dirname(input_video), "VIDEO_HD_SHORT.mp4")

    cmd = (
        f"ffmpeg -i {input_video} "
        f'-vf "crop=ih*9/16:ih, scale=1080:1920" '
        f"-c:v libx264 -preset ultrafast {output_video}"
    )

    subprocess.call(cmd, shell=True)

    return output_video


class Status(StrEnum):
    AUDIO_LOST = "Audio file lost"
    GETTING_AUDIO_DURATION = "Getting audio duration"
    FAILED_GETTING_AUDIO_DURATION = "Failed getting audio duration"
    PROCESSING_AUDIO_DESCRIPTION = "Processing audio description"
    FINISHED_PROCESSING_AUDIO_DESCRIPTION = "Finished processing audio description"
    STARTED_FINDING_MATCHING_VIDEOS_TO_AUDIO = (
        "Started finding matching videos to audio description provided"
    )
    FINISHED_FINDING_MATCHING_VIDEOS_TO_AUDIO = (
        "Finished finding matching videos to audio description"
    )
    MERGING_VIDEOS = "Merging videos"
    FINISHED_MERGING_VIDEOS = "Finished merging videos"
    STARTED_ADDING_AUDIO_TO_VIDEO = "Started adding audio to video"
    FINISHED_ADDING_AUDIO_TO_VIDEO = "Finished adding audio to video"
    CREATING_VIDEO_FOR_SHORTS = "Creating video for shorts"
    FINISHED_VIDEO_FOR_SHORTS = "Finished creating video for shorts"
    PROCESSING_COMPLETE = "Processing complete"
    CREATING_ZIP_WITH_VIDEOS = "Creating zip with videos for download"
    FINISHED_ZIP_WITH_VIDEOS = "Finished creating zip with videos for download"
    FAILED_TO_CREATE_VIDEO = "Failed to create video"


def set_status(status: Status, event_id: str):
    with open(f"./vids/{event_id}/status", "w") as f:
        f.write(status)


def get_status(event_id: str):
    status_path = f"./vids/{event_id}/status"
    if not os.path.exists(status_path):
        return Status.FAILED_TO_CREATE_VIDEO

    with open(status_path, "r") as f:
        status = f.read()
    return status


def get_videos_zippath(event_id: str):
    zip_filepath = f"./vids/{event_id}/{event_id}_videos.zip"
    if not os.path.exists(zip_filepath):
        return
    return zip_filepath


def cleanup_event(event_id: str):
    shutil.rmtree(f"./vids/{event_id}")


def create_videos_zippath(event_id: str):
    hdvideopath = f"./vids/{event_id}/VIDEO_HD.mp4"
    shorts_videopath = f"./vids/{event_id}/VIDEO_HD_SHORT.mp4"
    audio_description_path = f"./vids/{event_id}/audio_description.txt"

    zip_filepath = f"./vids/{event_id}/{event_id}_videos.zip"
    with zipfile.ZipFile(zip_filepath, "w") as zipf:
        zipf.write(hdvideopath, os.path.basename(hdvideopath))
        zipf.write(shorts_videopath, os.path.basename(shorts_videopath))
        zipf.write(audio_description_path, os.path.basename(audio_description_path))

    return zip_filepath


def create_video_from_audio(event_id: str, audio_description: str):
    try:
        save_path = f"./vids/{event_id}"
        if not os.path.exists(save_path):
            set_status(Status.AUDIO_LOST, event_id)
            return

        set_status(Status.GETTING_AUDIO_DURATION, event_id)
        audio_filepath = os.path.join(save_path, os.listdir(save_path)[0])
        audio_duration = get_duration_in_seconds(audio_filepath)
        if not audio_duration:
            set_status(Status.FAILED_GETTING_AUDIO_DURATION, event_id)
            return

        set_status(Status.PROCESSING_AUDIO_DESCRIPTION, event_id)

        punctuation_regex = re.compile(r"[^\w\s,]", re.UNICODE)
        audio_description = punctuation_regex.sub("", audio_description)
        audio_description = audio_description.replace(",", " ")

        descriptionSplit = [
            d.strip() for d in audio_description.split(" ") if len(d.strip()) > 3
        ]

        counted_words = {
            word: descriptionSplit.count(word) for word in descriptionSplit
        }
        sorted_counted_words = sorted(
            counted_words.items(), key=lambda kv: kv[1], reverse=True
        )

        if len(sorted_counted_words) > audio_duration:
            sorted_counted_words = sorted_counted_words[0:audio_duration]

        set_status(Status.FINISHED_PROCESSING_AUDIO_DESCRIPTION, event_id)

        set_status(Status.STARTED_FINDING_MATCHING_VIDEOS_TO_AUDIO, event_id)
        word_video = {}
        total_duration = 0
        for word in sorted_counted_words:
            video_filepath = get_video_for_query(word, save_path)
            if video_filepath:
                video_duration = get_duration_in_seconds(video_filepath)
                total_duration += video_duration
                word_video[word] = video_filepath
                if total_duration > audio_duration:
                    break

        video_filepaths = list(word_video.values())

        set_status(Status.FINISHED_FINDING_MATCHING_VIDEOS_TO_AUDIO, event_id)

        set_status(Status.MERGING_VIDEOS, event_id)

        if len(video_filepaths) > 1:
            big_video = merge_videos(video_filepaths, audio_duration)
        else:
            big_video = video_filepaths[0]

        set_status(Status.FINISHED_MERGING_VIDEOS, event_id)

        set_status(Status.STARTED_ADDING_AUDIO_TO_VIDEO, event_id)
        hd_video_path = add_audio_to_video(big_video)
        set_status(Status.FINISHED_ADDING_AUDIO_TO_VIDEO, event_id)

        set_status(Status.CREATING_VIDEO_FOR_SHORTS, event_id)
        shorts_video_path = create_shorts_video(hd_video_path)
        set_status(Status.CREATING_VIDEO_FOR_SHORTS, event_id)

        set_status(Status.CREATING_ZIP_WITH_VIDEOS, event_id)

        with open(f"{save_path}/audio_description.txt", "w") as f:
            f.write(f"hd_video_path: {os.path.basename(hd_video_path)}\n")
            f.write(f"shorts_video_path: {os.path.basename(shorts_video_path)}\n")
            f.write(f"audio_description:\n{audio_description}")

        create_videos_zippath(event_id)

        set_status(Status.FINISHED_ZIP_WITH_VIDEOS, event_id)

        set_status(Status.PROCESSING_COMPLETE, event_id)

    except Exception as err:
        print(err)
        set_status(Status.FAILED_TO_CREATE_VIDEO, event_id)
