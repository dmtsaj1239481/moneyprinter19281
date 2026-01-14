import os
import requests
import asyncio
import edge_tts
import time
from loguru import logger
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from datetime import datetime
from typing import List, Generator
from app.utils import utils
from app.config import config
from app.services import llm, voice

def get_time(): 
    return datetime.now().strftime("%H:%M:%S")

def get_720p_url(v_data, v_type):
    files = v_data['video_files']
    target_w = 1280 if v_type == "landscape" else 720
    for f in files:
        if f['width'] == target_w: 
            return f['link']
    return files[0]['link']

from proglog import ProgressBarLogger
class LiteProgressLogger(ProgressBarLogger):
    def __init__(self, start_logs=""):
        super().__init__()
        self.full_logs = start_logs
        self.last_pct = -1
        
    def callback(self, **kwargs):
        index = kwargs.get('index', 0)
        total = kwargs.get('total', 1)
        percent = int((index / total) * 100)
        
        if percent % 10 == 0 and percent != self.last_pct:
            self.last_pct = percent
            # We can't easily yield from here, so we update the log string
            # But we want the UI to see it. In lite engine, logs are passed by reference or accumulated.
            logger.info(f"🔨 [Stitching Progress] {percent}%")

async def generate_lite_video(
    video_subject: str,
    video_script: str,
    voice_name: str,
    video_aspect: str = "landscape",
    voice_rate: float = 1.0,
    voice_pitch: int = 0,
    pexels_api_key: str = "",
    fast_narration: bool = False,
) -> Generator:
    
    start_time = time.time()
    task_id = utils.get_uuid()
    temp_dir = utils.storage_dir(f"tasks/{task_id}", create=True)
    final_output = os.path.join(temp_dir, "final_video.mp4")
    
    logs = f"[{get_time()}] 🚀 LITE ENGINE INITIALIZED (720p 30FPS)\n"
    logs += f"[{get_time()}] 📁 Working Directory: {temp_dir}\n"
    yield None, logs
    
    sentences = [s.strip() for s in video_script.split('.') if len(s.strip()) > 5]
    total_scenes = len(sentences)
    logs += f"[{get_time()}] 📄 Script analyzed. Scenes to generate: {total_scenes}\n"
    yield None, logs
    
    # 2. Parallel Processing
    from concurrent.futures import ThreadPoolExecutor
    
    def process_scene(i, sent):
        scene_start = time.time()
        try:
            msg = f"[{get_time()}] 🎬 Scene {i+1}/{total_scenes}: Character count: {len(sent)}"
            
            # Keyword Extraction
            kw_terms = llm.generate_terms(video_subject, sent, amount=1)
            kw = kw_terms[0] if kw_terms else "nature"
            msg += f" | Key: '{kw}'"
            
            # Audio Generation
            a_path = os.path.join(temp_dir, f"audio_{i}.mp3")
            rate_percent = round((voice_rate - 1.0) * 100)
            rate_str = f"{'+' if rate_percent >= 0 else ''}{rate_percent}%"
            pitch_str = f"{'+' if voice_pitch >= 0 else ''}{voice_pitch}Hz"
            
            async def run_tts():
                input_text = sent
                if fast_narration:
                    input_text = voice.make_text_breathless(sent)
                await edge_tts.Communicate(input_text, voice_name, pitch=pitch_str, rate=rate_str).save(a_path)
            asyncio.run(run_tts())
            
            # if fast_narration:
            #     voice.trim_silence_from_audio(a_path)
            
            if not os.path.exists(a_path) or os.path.getsize(a_path) == 0:
                return None, f"[{get_time()}] ❌ Scene {i+1} Error: Audio generation failed"
                
            try:
                a_clip = AudioFileClip(a_path)
                dur = getattr(a_clip, 'duration', 0)
                if dur <= 0:
                    # Try to reload or use a default
                    dur = 5.0 # Fallback
            except Exception:
                dur = 5.0
                
            msg += f" | Audio: {dur:.2f}s"

            # Video Procurement
            headers = {"Authorization": pexels_api_key}
            orientation = "landscape" if video_aspect == "landscape" else "portrait"
            search_url = f"https://api.pexels.com/videos/search?query={kw}&per_page=1&orientation={orientation}"
            res = requests.get(search_url, headers=headers).json()
            
            if res.get('videos'):
                v_url = get_720p_url(res['videos'][0], video_aspect)
                v_path = os.path.join(temp_dir, f"video_{i}.mp4")
                with open(v_path, 'wb') as f:
                    f.write(requests.get(v_url).content)
                
                if not os.path.exists(v_path) or os.path.getsize(v_path) == 0:
                    return None, f"[{get_time()}] ❌ Scene {i+1} Error: Video download failed"
                    
                v_clip = VideoFileClip(v_path)
                if not v_clip or not hasattr(v_clip, 'duration') or v_clip.duration <= 0:
                    return None, f"[{get_time()}] ❌ Scene {i+1} Error: Invalid video duration"
                    
                msg += f" | Pexels V: {v_clip.duration:.2f}s"
                
                if v_clip.duration < a_clip.duration:
                    v_clip = v_clip.loop(duration=a_clip.duration)
                else:
                    v_clip = v_clip.subclipped(0, a_clip.duration)
                
                w_target, h_target = (1280, 720) if video_aspect == "landscape" else (720, 1280)
                v_clip = v_clip.resized(new_size=(w_target, h_target)).with_audio(a_clip)
                
                scene_end = time.time()
                logger.debug(f"Scene {i+1} completed in {scene_end - scene_start:.2f}s")
                return v_clip, msg + f" | ✅ Done ({scene_end-scene_start:.1f}s)"
            return None, msg + " | ❌ No video found"
        except Exception as e:
            import traceback
            logger.error(f"Error in scene {i}: {str(e)}\n{traceback.format_exc()}")
            return None, f"[{get_time()}] ❌ Scene {i+1} Error: {str(e)}"

    logs += f"[{get_time()}] ⚡ STAGE 1: Parallel Processing (Audio + Footage)..."
    yield None, logs
    
    with ThreadPoolExecutor(max_workers=min(total_scenes, 8)) as executor:
        results = list(executor.map(lambda x: process_scene(*x), enumerate(sentences)))
    
    final_clips = []
    for clip, scene_log in results:
        logs += f"\n{scene_log}"
        if clip:
            final_clips.append(clip)
            
    success_count = len(final_clips)
    logs += f"\n[{get_time()}] ✅ Parallel Processing Complete. {success_count}/{total_scenes} scenes ready."
    yield None, logs

    # 3. Final Export
    if final_clips:
        est_stitch_time = len(final_clips) * 2 # Rough estimate: 2s per scene for stitch
        logs += f"\n[{get_time()}] 🛠️ STAGE 2: Stitching & Encoding (Est: {est_stitch_time}s)..."
        yield None, logs
        
        try:
            final_video = concatenate_videoclips(final_clips, method="compose")
            
            ffmpeg_params = [
                "-preset", "ultrafast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", "30" 
            ]
            
            # Progress tracking for stitch
            class InternalLogger(ProgressBarLogger):
                def callback(self, **kwargs):
                    idx = kwargs.get('index', 0)
                    total = kwargs.get('total', 1)
                    if total > 0:
                        p = int((idx / total) * 100)
                        if p % 10 == 0:
                            logger.info(f"🔨 [Lite Stitch] {p}%")

            final_video.write_videofile(
                final_output, 
                fps=30, 
                codec="libx264", 
                audio_codec="aac",
                logger=InternalLogger(),
                threads=4,
                ffmpeg_params=ffmpeg_params
            )
            
            total_time = time.time() - start_time
            logs += f"\n[{get_time()}] 🎉 VIDEO GENERATED SUCCESSFULLY!"
            logs += f"\n[{get_time()}] ⏱️ Total Time: {total_time:.2f} seconds"
            logs += f"\n[{get_time()}] 📂 Location: {final_output}"
            
            for clip in final_clips: clip.close()
            final_video.close()
            
            yield final_output, logs
        except Exception as e:
            logs += f"\n[{get_time()}] ❌ STITCHING ERROR: {str(e)}"
            yield None, logs
    else:
        logs += f"\n[{get_time()}] ❌ FAILED: No clips were successful."
        yield None, logs
