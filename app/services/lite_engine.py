#!/usr/bin/env python3
import os
import requests
import asyncio
import edge_tts
from loguru import logger
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from datetime import datetime
from typing import List, Generator
from app.utils import utils
from app.config import config
from app.services import llm

def get_time(): 
    return datetime.now().strftime("%H:%M:%S")

def get_720p_url(v_data, v_type):
    files = v_data['video_files']
    # Target resolution: 1280x720 for landscape, 720x1280 for portrait
    target_w = 1280 if v_type == "landscape" else 720
    for f in files:
        if f['width'] == target_w: 
            return f['link']
    return files[0]['link']

async def generate_lite_video(
    video_subject: str,
    video_script: str,
    voice_name: str,
    video_aspect: str = "landscape", # "landscape" or "portrait"
    voice_rate: float = 1.0,
    voice_pitch: int = 0,
    pexels_api_key: str = "",
) -> Generator:
    
    # 1. Initialization
    task_id = utils.get_uuid()
    temp_dir = utils.storage_dir(f"tasks/{task_id}", create=True)
    final_output = os.path.join(temp_dir, "final_video.mp4")
    
    logs = f"[{get_time()}] 🚀 Starting Lite Engine (720p @ 30FPS)...\n"
    yield None, logs
    
    # Split script into sentences
    sentences = [s.strip() for s in video_script.split('.') if len(s.strip()) > 5]
    logs += f"[{get_time()}] 📄 Total Scenes: {len(sentences)}\n"
    yield None, logs
    
    final_clips = []
    
    # 2. Process each sentence
    for i, sent in enumerate(sentences):
        scene_log = f"\n🎬 --- SCENE {i+1}/{len(sentences)} ---\n"
        logs += scene_log
        yield None, logs
        
        # Keyword Extraction
        try:
            logs += f"[{get_time()}] 🧠 Keyword Extraction...\n"
            yield None, logs
            
            # Use the existing LLM service to get a keyword
            # We ask for only 1 search term
            terms = llm.generate_terms(video_subject, sent, amount=1)
            if isinstance(terms, list) and len(terms) > 0:
                kw = terms[0]
            else:
                kw = "nature"
                
            logs += f"[{get_time()}] ✅ Keyword: '{kw}'\n"
            yield None, logs
        except Exception as e:
            logger.error(f"Lite Engine LLM error: {e}")
            kw = "nature"

        # Audio Generation (Edge-TTS)
        logs += f"[{get_time()}] 🎙️ Generating Audio...\n"
        yield None, logs
        a_path = os.path.join(temp_dir, f"audio_{i}.mp3")
        
        # Convert rate to edge_tts format e.g. "+0%"
        rate_percent = round((voice_rate - 1.0) * 100)
        rate_str = f"{'+' if rate_percent >= 0 else ''}{rate_percent}%"
        pitch_str = f"{'+' if voice_pitch >= 0 else ''}{voice_pitch}Hz"
        
        await edge_tts.Communicate(sent, voice_name, pitch=pitch_str, rate=rate_str).save(a_path)
        a_clip = AudioFileClip(a_path)

        # Video Procurement (Pexels)
        logs += f"[{get_time()}] ⬇️ Downloading 720p Footage...\n"
        yield None, logs
        
        if not pexels_api_key:
            pexels_api_keys = config.app.get("pexels_api_keys", [])
            if pexels_api_keys:
                pexels_api_key = pexels_api_keys[0]
        
        headers = {"Authorization": pexels_api_key}
        # orientation maps to pexels orientation: "landscape", "portrait" or "square"
        orientation = "landscape" if video_aspect == "landscape" else "portrait"
        
        try:
            search_url = f"https://api.pexels.com/videos/search?query={kw}&per_page=1&orientation={orientation}"
            res = requests.get(search_url, headers=headers).json()
            
            if res.get('videos'):
                v_url = get_720p_url(res['videos'][0], video_aspect)
                v_path = os.path.join(temp_dir, f"video_{i}.mp4")
                with open(v_path, 'wb') as f:
                    f.write(requests.get(v_url).content)
                
                # Processing with MoviePy
                logs += f"[{get_time()}] ✂️ Processing Clip...\n"
                yield None, logs
                
                v_clip = VideoFileClip(v_path)
                
                # Loop video if it's shorter than audio
                if v_clip.duration < a_clip.duration:
                    v_clip = v_clip.loop(duration=a_clip.duration)
                else:
                    v_clip = v_clip.subclipped(0, a_clip.duration)
                
                # Resize to target
                w_target, h_target = (1280, 720) if video_aspect == "landscape" else (720, 1280)
                v_clip = v_clip.resized(new_size=(w_target, h_target)).with_audio(a_clip)
                final_clips.append(v_clip)
                
                logs += f"[{get_time()}] ✅ Scene {i+1} processed\n"
                yield None, logs
            else:
                logs += f"[{get_time()}] ⚠️ No video found for '{kw}'\n"
                yield None, logs
        except Exception as e:
            logger.error(f"Lite Engine Pexels/Video error: {e}")
            logs += f"[{get_time()}] ❌ Error processing scene {i+1}: {str(e)}\n"
            yield None, logs

    # 3. Final Export
    if final_clips:
        logs += f"\n[{get_time()}] 🔨 STITCHING FINAL VIDEO (720p 30fps)...\n"
        logs += f"[{get_time()}] ⚠️ NOTE: Render progress check console for progress bar.\n"
        yield None, logs
        
        try:
            final_video = concatenate_videoclips(final_clips, method="compose")
            # Using ultrafast as requested
            final_video.write_videofile(
                final_output, 
                fps=30, 
                codec="libx264", 
                preset='ultrafast', 
                logger=None,
                threads=4
            )
            
            # Cleanup
            for clip in final_clips:
                clip.close()
            final_video.close()
            
            logs += f"[{get_time()}] 🎉 VIDEO READY! Path: {final_output}\n"
            yield final_output, logs
        except Exception as e:
            logger.error(f"Lite Engine Export error: {e}")
            logs += f"[{get_time()}] ❌ Final Export Error: {str(e)}\n"
            yield None, logs
    else:
        logs += f"[{get_time()}] ❌ No clips were generated. Check your Pexels key or internet connection.\n"
        yield None, logs
