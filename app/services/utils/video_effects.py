from moviepy import Clip, vfx


# FadeIn
def fadein_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeIn(t)])


# FadeOut
def fadeout_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeOut(t)])


# SlideIn
def slidein_transition(clip: Clip, t: float, side: str) -> Clip:
    return clip.with_effects([vfx.SlideIn(t, side)])


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    return clip.with_effects([vfx.SlideOut(t, side)])


# CrossFade
def crossfadein_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.CrossFadeIn(t)])


def crossfadeout_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.CrossFadeOut(t)])
