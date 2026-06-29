import os
import subprocess
import sys

if __package__:
    from .dkaraoke import app, audio_server, cache, constants, lyrics, messaging, paths, pipeline, processes, stems, youtube
else:
    from dkaraoke import app, audio_server, cache, constants, lyrics, messaging, paths, pipeline, processes, stems, youtube

_APP_EXECUTE_MESSAGE = app.execute_message
_APP_HANDLE_MESSAGE = app.handle_message
_APP_MAIN = app.main
_LYRICS_RUNNER_PATH = lyrics.lyrics_runner_path
_LYRICS_ALIGN = lyrics.align_lyrics
_LYRICS_SILERO_VAD_RUNNER_PATH = lyrics.silero_vad_runner_path
_LYRICS_ALIGN_SILERO_VAD = lyrics.align_lyrics_with_silero_vad
_PIPELINE_CHECK_CACHE = pipeline.check_cache
_PIPELINE_EXTRACT_LYRICS_TIMINGS = pipeline.extract_lyrics_timings
_PIPELINE_PUBLISH_STEMS_AND_COMPLETE = pipeline.publish_stems_and_complete
_PIPELINE_RUN_DOWNLOAD = pipeline.run_download
_STEMS_COMPRESS = stems.compress_stems
_STEMS_RESOLVE_CACHED = stems.resolve_cached_stems
_YOUTUBE_HAS_AUTH_ERROR = youtube.has_auth_error
_YOUTUBE_REQUIRE_TOOLS = youtube.require_tools
_YOUTUBE_RUNTIME_ARGS = youtube.ytdlp_runtime_args
_YOUTUBE_WRITE_COOKIE_FILE = youtube.write_cookie_file

AUTH_ERROR_MARKERS = constants.AUTH_ERROR_MARKERS
LYRICS_TIMEOUT_SECONDS = constants.LYRICS_TIMEOUT_SECONDS
STEM_WAIT_TIMEOUT_SECONDS = constants.STEM_WAIT_TIMEOUT_SECONDS
NativeMessagingDisconnected = messaging.NativeMessagingDisconnected

begin_stem_job = paths.begin_stem_job
clean_metadata_text = lyrics.clean_metadata_text
complete_job = pipeline.complete_job
fetch_lrclib_lyrics = lyrics.fetch_lrclib_lyrics
finish_stem_job = paths.finish_stem_job
format_remaining_time = processes.format_remaining_time
lrclib_candidate_score = lyrics.lrclib_candidate_score
parse_lrc_segments = lyrics.parse_lrc_segments
prepare_lyrics = lyrics.prepare_lyrics
register_audio = audio_server.register_audio
roformer_progress_from_line = processes.roformer_progress_from_line
run_roformer = pipeline.run_roformer
send_job = messaging.send_job
send_message = messaging.send_message
send_stems_ready = pipeline.send_stems_ready
stem_paths = stems.stem_paths
stop_audio_server = audio_server.stop_audio_server
unlink_best_effort = cache.unlink_best_effort
validate_stem_mp3 = stems.validate_stem_mp3
song_metadata_from_title = lyrics.song_metadata_from_title


def _sync_patchable_globals():
    app.execute_message = execute_message
    app.app_download_dir = app_download_dir
    app.extract_lyrics_timings = extract_lyrics_timings
    app.fetch_lrclib_lyrics = fetch_lrclib_lyrics
    app.handle_message = handle_message
    app.read_message = read_message
    app.send_job = send_job
    app.stop_audio_server = stop_audio_server

    lyrics.lyrics_runner_path = lyrics_runner_path
    lyrics.align_lyrics = align_lyrics
    lyrics.silero_vad_runner_path = silero_vad_runner_path
    lyrics.align_lyrics_with_silero_vad = align_lyrics_with_silero_vad
    lyrics.send_job = send_job
    lyrics.subprocess = subprocess

    pipeline.app_download_dir = app_download_dir
    pipeline.compress_stems = compress_stems
    pipeline.complete_job = complete_job
    pipeline.has_auth_error = has_auth_error
    pipeline.fetch_lrclib_lyrics = fetch_lrclib_lyrics
    pipeline.prepare_lyrics = prepare_lyrics
    pipeline.publish_stems_and_complete = publish_stems_and_complete
    pipeline.register_audio = register_audio
    pipeline.require_tools = require_tools
    pipeline.resolve_cached_stems = resolve_cached_stems
    pipeline.run_roformer = run_roformer
    pipeline.send_job = send_job
    pipeline.send_stems_ready = send_stems_ready
    pipeline.stem_job_active = stem_job_active
    pipeline.stem_ready_event = stem_ready_event
    pipeline.subprocess = subprocess
    pipeline.timing_job_lock = timing_job_lock
    pipeline.unlink_best_effort = unlink_best_effort
    pipeline.write_cookie_file = write_cookie_file
    pipeline.ytdlp_runtime_args = ytdlp_runtime_args

    stems.compress_stems = compress_stems
    stems.send_job = send_job
    stems.subprocess = subprocess
    stems.unlink_best_effort = unlink_best_effort
    stems.validate_stem_mp3 = validate_stem_mp3

    youtube.require_tools = require_tools
    youtube.subprocess = subprocess
    youtube.ytdlp_runtime_args = ytdlp_runtime_args


def app_download_dir(video_id):
    return paths.app_download_dir(video_id)


def check_cache(job_id, raw_url):
    _sync_patchable_globals()
    return _PIPELINE_CHECK_CACHE(job_id, raw_url)


def compress_stems(job_id, instrumental_wav, vocals_wav):
    _sync_patchable_globals()
    return _STEMS_COMPRESS(job_id, instrumental_wav, vocals_wav)


def execute_message(message):
    _sync_patchable_globals()
    return _APP_EXECUTE_MESSAGE(message)


def extract_lyrics_timings(
    job_id, raw_url, requested_text,
    timing_method=constants.DEFAULT_LYRICS_TIMING_METHOD,
    timing_source=constants.DEFAULT_LYRICS_TIMING_SOURCE,
    cookies=None,
):
    _sync_patchable_globals()
    return _PIPELINE_EXTRACT_LYRICS_TIMINGS(
        job_id, raw_url, requested_text, timing_method, timing_source, cookies,
    )


def handle_message(message):
    _sync_patchable_globals()
    return _APP_HANDLE_MESSAGE(message)


def has_auth_error(output_text):
    return _YOUTUBE_HAS_AUTH_ERROR(output_text)


def lyrics_runner_path():
    return _LYRICS_RUNNER_PATH()


def silero_vad_runner_path():
    return _LYRICS_SILERO_VAD_RUNNER_PATH()


def main():
    _sync_patchable_globals()
    return _APP_MAIN()


def publish_stems_and_complete(job_id, video_id, instrumental_path, vocals_path, cache_hit=False):
    _sync_patchable_globals()
    return _PIPELINE_PUBLISH_STEMS_AND_COMPLETE(
        job_id, video_id, instrumental_path, vocals_path, cache_hit=cache_hit,
    )


def read_message():
    return messaging.read_message()


def require_tools():
    return _YOUTUBE_REQUIRE_TOOLS()


def resolve_cached_stems(job_id, stem_dir):
    _sync_patchable_globals()
    return _STEMS_RESOLVE_CACHED(job_id, stem_dir)


def run_download(job_id, raw_url, cookies, lyrics_timing=None):
    _sync_patchable_globals()
    return _PIPELINE_RUN_DOWNLOAD(job_id, raw_url, cookies, lyrics_timing)


def stem_job_active(video_id):
    return paths.stem_job_active(video_id)


def stem_ready_event(video_id):
    return paths.stem_ready_event(video_id)


def timing_job_lock(video_id):
    return paths.timing_job_lock(video_id)


def align_lyrics(job_id, vocals_path, lyrics_text):
    _sync_patchable_globals()
    return _LYRICS_ALIGN(job_id, vocals_path, lyrics_text)


def align_lyrics_with_silero_vad(job_id, vocals_path, lyrics_text):
    _sync_patchable_globals()
    return _LYRICS_ALIGN_SILERO_VAD(job_id, vocals_path, lyrics_text)


def validate_youtube_url(raw_url):
    return paths.validate_youtube_url(raw_url)


def video_id_from_url(raw_url):
    return paths.video_id_from_url(raw_url)


def write_cookie_file(cookies):
    return _YOUTUBE_WRITE_COOKIE_FILE(cookies)


def ytdlp_runtime_args():
    return _YOUTUBE_RUNTIME_ARGS()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
