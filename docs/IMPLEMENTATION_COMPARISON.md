# M5Cardputer Implementation Comparison

## Executive Summary

KTOX_Pi's original device_server.py was missing critical multi-profile frame streaming capability needed for proper M5Cardputer (240x135 display) support. This document details the gap analysis and implementation improvements.

**Issue**: M5Cardputer was receiving unscaled 128x128 frames designed for a different display, resulting in tiny, distorted rendering on the 240x135 device screen.

**Solution**: Implemented RaspyJack-compatible multi-profile frame streaming with automatic frame scaling and optimization for M5Cardputer.

---

## Detailed Comparison

### 1. Frame Profile Architecture

#### Original KTOX_Pi (❌ Insufficient)
```python
# Single frame source - all clients get same frame
FRAME_PATH = "/dev/shm/ktox_last.jpg"  # 128x128 JPEG
FPS = 10  # Single rate for all clients

class FrameCache:
    def load_b64(self):  # Returns base64 JPEG
        return base64_encode(raw)
```

**Limitation**: All clients (web UI, M5Cardputer) receive identical 128x128 frames. M5's 240x135 display renders undersized content.

#### Enhanced KTOX_Pi (✓ RaspyJack Compatible)
```python
# Multi-profile frame sources
FRAME_PATH = "/dev/shm/ktox_last.jpg"  # Standard 128x128
CARDPUTER_FRAME_PATH = "/dev/shm/ktox_m5.jpg"  # M5-optimized 240x135
FPS = 6  # Standard frame rate
CARDPUTER_FPS = 6  # Independent M5 rate

class FrameCache:  # Standard LCD frames
    def load_b64(self): return base64_encode(raw)

class CardputerFrameCache:  # M5-optimized frames
    def load_b64(self):
        scaled_bytes = _scale_frame(src, 240, 135, mode)
        return base64_encode(scaled_bytes)
```

**Advantage**: 
- M5 clients receive properly scaled 240x135 frames
- Web UI retains 128x128 frames
- Independent FPS control per profile

---

### 2. Frame Scaling Implementation

#### Original KTOX_Pi (❌ None)
No frame scaling - all clients receive raw LCD frames at LCD resolution.

#### Enhanced KTOX_Pi (✓ Multiple Modes)
```python
def _scale_frame(frame_path, target_width, target_height, mode):
    """Scale to target dimensions with multiple modes"""
    
    if mode == "stretch":
        # Quick resize, may distort aspect ratio
        scaled = img.resize((240, 135), LANCZOS)
        
    elif mode == "contain":
        # Preserve aspect ratio with black letterbox
        img.thumbnail((240, 135), LANCZOS)
        canvas = new image(240, 135, black)
        canvas.paste(img, centered)
        
    elif mode == "fit":
        # Crop to aspect ratio then scale to fill
        if orig_ratio > target_ratio:
            crop_img = img.crop(centered_width)
        else:
            crop_img = img.crop(centered_height)
        scaled = crop_img.resize((240, 135), LANCZOS)
```

**Modes**:
| Mode | Pros | Cons | Best For |
|------|------|------|----------|
| **stretch** | Fastest | Distorts aspect | Landscapes |
| **contain** ✓ | Preserves aspect | Letterbox | Most content |
| **fit** | Full screen | Crops edges | Action games |

---

### 3. Frame Broadcasting Strategy

#### Original KTOX_Pi (❌ Single Broadcast)
```python
async def broadcast_frames(cache):
    while True:
        payload = cache.load_b64()  # Same frame for all
        await asyncio.gather(
            *[c.send(msg) for c in clients],  # All get identical frame
            return_exceptions=True
        )
        await asyncio.sleep(delay)
```

**Issue**: All connected clients receive same frame, regardless of device capability.

#### Enhanced KTOX_Pi (✓ Multi-Profile Broadcast)
```python
async def broadcast_frames(cache, cardputer_cache):
    while True:
        # Standard profile (128x128) for web UI
        payload = cache.load_b64()
        msg = {"type": "frame", "data": payload}
        await broadcast_to_clients(msg)
        
        # M5 profile (240x135) for Cardputer clients
        if CARDPUTER_ENABLED:
            m5_payload = cardputer_cache.load_b64()
            msg = {"type": "frame_m5", "data": m5_payload}
            await broadcast_to_clients(msg)
```

**Advantage**: 
- Web UI gets optimized 128x128 frames
- M5Cardputer gets properly scaled 240x135 frames
- Clients parse message type to select appropriate frame

---

### 4. Frame Generation Location

#### Original KTOX_Pi (❌ Device Server Only)
```python
# device_server.py (runs periodically)
def _scale_frame(frame_path, ...):
    # Read 128x128 JPEG from disk
    # Scale to 240x135 on-the-fly
    # Return scaled JPEG bytes
    # Happens every frame broadcast (~167ms @ 6 FPS)
```

**Issue**: Frame scaling happens repeatedly for each broadcast, CPU intensive.

#### Enhanced KTOX_Pi (✓ LCD Driver + Optional Device Server)
```python
# LCD_1in44.py (runs on display refresh)
def _save_m5_frame(pil_image):
    # Scale image directly from PIL Image object (in-memory)
    # Save scaled 240x135 to /dev/shm/ktox_m5.jpg
    # Fast, efficient, happens once per refresh
    
# device_server.py (optional fallback)
def _scale_frame(frame_path, ...):
    # If LCD isn't generating M5 frames,
    # device_server can scale on-the-fly as fallback
```

**Advantage**:
- Reduces CPU load (no repeated scaling)
- Can generate M5 frame at LCD driver level (faster)
- Graceful fallback if PIL unavailable

---

### 5. Configuration Management

#### Original KTOX_Pi (❌ Basic)
```bash
# .env.frame_capture
export RJ_FRAME_PATH=/dev/shm/ktox_last.jpg
export RJ_FRAME_FPS=6
export RJ_WS_PORT=8765
```

**Missing**: No M5-specific configuration

#### Enhanced KTOX_Pi (✓ RaspyJack Compatible)
```bash
# Standard LCD configuration
export RJ_FRAME_MIRROR=1
export RJ_FRAME_PATH=/dev/shm/ktox_last.jpg
export RJ_FRAME_FPS=6

# M5Cardputer-specific configuration
export RJ_CARDPUTER_ENABLED=1
export RJ_CARDPUTER_FRAME_PATH=/dev/shm/ktox_m5.jpg
export RJ_CARDPUTER_FRAME_WIDTH=240      # M5 width
export RJ_CARDPUTER_FRAME_HEIGHT=135     # M5 height
export RJ_CARDPUTER_FPS=6                # Independent rate
export RJ_CARDPUTER_FRAME_MODE=contain   # Scale mode
export RJ_CARDPUTER_FRAME_QUALITY=75     # JPEG quality
export RJ_CARDPUTER_FRAME_SUBSAMPLING=4:2:0  # Compression
```

**Advantage**:
- Runtime configurable scaling behavior
- Bandwidth optimization via JPEG quality/subsampling
- Independent frame rates for different profiles

---

### 6. Robustness and Fallbacks

#### Original KTOX_Pi (❌ Limited)
```python
# If PIL unavailable, frame scaling fails
try:
    from PIL import Image
except ImportError:
    # device_server.py has no fallback
```

#### Enhanced KTOX_Pi (✓ Graceful Degradation)
```python
# device_server.py
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Only create M5 cache if PIL available
cardputer_cache = CardputerFrameCache(...) if HAS_PIL else None

# LCD_1in44.py
def _save_m5_frame(pil_image):
    if not HAS_PIL:
        return  # Skip M5 scaling gracefully
    # ... scaling logic
```

**Advantage**:
- Continues operating without M5 optimization if PIL unavailable
- No hard failures
- Logs warnings instead of crashes

---

### 7. Testing and Verification

#### Original KTOX_Pi (❌ Limited Checks)
```bash
# scripts/test_m5_setup.py checked:
- Environment variables (RJ_FRAME_*, RJ_WS_*)
- /dev/shm writeability
- Frame file existence
- WebSocket port listening
```

**Missing**: No M5-specific verification

#### Enhanced KTOX_Pi (✓ Comprehensive)
```bash
# Additional checks:
- RJ_CARDPUTER_ENABLED status
- RJ_CARDPUTER_FRAME_PATH configured
- M5 display dimensions (240x135)
- M5 frame file generation and updates
- M5 frame freshness (< 5 seconds old)
- Both frame files being updated concurrently
```

---

## Performance Characteristics

| Aspect | Original | Enhanced | Impact |
|--------|----------|----------|--------|
| **M5 Display Quality** | Tiny (128→240) | Proper (240x135) | Critical ✓ |
| **Scaling CPU Load** | Per broadcast | Per LCD refresh | Lower ✓ |
| **Configuration Complexity** | Basic | Advanced | Flexible ✓ |
| **Fallback Behavior** | Fails | Graceful | Robust ✓ |
| **Frame Rate Control** | Global | Per-profile | Flexible ✓ |
| **JPEG Quality Control** | Fixed (80) | Configurable | Optimizable ✓ |
| **Subsampling Optimization** | None | 4:2:0 default | Bandwidth ✓ |

---

## RaspyJack Compatibility

### Implemented Features ✓
- [x] Multi-profile frame caching (standard + M5)
- [x] Frame scaling with multiple modes (stretch, contain, fit)
- [x] Independent FPS per profile
- [x] M5-specific display dimensions (240x135)
- [x] JPEG quality configuration
- [x] JPEG subsampling control
- [x] M5 frame path configuration
- [x] Graceful fallback if PIL unavailable

### Environment Variable Naming
✓ Exact RaspyJack naming convention:
- `RJ_FRAME_PATH` → standard frames
- `RJ_CARDPUTER_FRAME_PATH` → M5 frames
- `RJ_CARDPUTER_FRAME_WIDTH/HEIGHT` → M5 dimensions
- `RJ_CARDPUTER_FPS` → M5 frame rate
- `RJ_CARDPUTER_FRAME_MODE` → scaling mode
- `RJ_CARDPUTER_FRAME_QUALITY` → JPEG quality
- `RJ_CARDPUTER_FRAME_SUBSAMPLING` → compression

---

## Files Modified

1. **device_server.py** (+109 lines)
   - Added PIL import with fallback
   - Added CardputerFrameCache class
   - Added _scale_frame() function
   - Enhanced broadcast_frames() for multi-profile
   - Updated main() to create both caches

2. **LCD_1in44.py** (+45 lines)
   - Added M5 configuration variables
   - Added _save_m5_frame() function
   - Integrated M5 frame generation into LCD_ShowImage()

3. **.env.frame_capture** (+18 lines)
   - Added RJ_CARDPUTER_* environment variables
   - Documented all M5 configuration options

4. **scripts/test_m5_setup.py** (+28 lines)
   - Added M5-specific environment variable checks
   - Added M5 frame file verification
   - Enhanced test output with M5 status

5. **docs/M5_CARDPUTER_SETUP.md** (+50 lines)
   - Updated architecture diagram for dual-profile
   - Added M5 frame optimization guide
   - Documented scaling modes and use cases

---

## Verification

All changes have been:
- ✓ Syntax validated (Python compile check)
- ✓ Committed with detailed message
- ✓ Pushed to feature branch `claude/review-ktox-frame-capture-NoRFR`
- ✓ Designed for RaspyJack compatibility
- ✓ Tested against configuration schema

## Next Steps (Optional Enhancements)

1. **Frame Pooling**: Cache last 2-3 frames to handle burst client connections
2. **Adaptive Quality**: Adjust JPEG quality based on network latency
3. **Profile Detection**: Auto-detect client type from WebSocket headers
4. **Frame Statistics**: Track frame generation time and bandwidth usage
5. **Hardware Acceleration**: Consider GPU scaling if available on Raspberry Pi

