 # -*- coding:UTF-8 -*-
 ##
 # | file      	:	LCD_1IN44.py
 # |	version		:	V2.0
 # | date		:	2018-07-16
 # | function	:	On the ST7735S chip driver and clear screen, drawing lines, drawing, writing 
 #					and other functions to achieve
 #
 # Permission is hereby granted, free of charge, to any person obtaining a copy
 # of this software and associated documnetation files (the "Software"), to deal
 # in the Software without restriction, including without limitation the rights
 # to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 # copies of the Software, and to permit persons to  whom the Software is
 # furished to do so, subject to the following conditions:
 #
 # The above copyright notice and this permission notice shall be included in
 # all copies or substantial portions of the Software.
 #
 # THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 # IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 # FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 # AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 # LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 # OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 # THE SOFTWARE.
 #

import LCD_Config
import RPi.GPIO as GPIO
import time
import numpy as np
import os
from PIL import Image as PILImage

from display_profiles import get_display_profile

LCD_1IN44 = 1
LCD_1IN8 = 0

# Native dimensions for the original Waveshare 1.44" ST7735 panel.
# The public LCD_WIDTH/LCD_HEIGHT constants below follow the active display
# profile so compatibility payloads that allocate from LCD_1in44 render into
# the same canvas size used by _display_helper.ScaledDraw.
_LCD_NATIVE_WIDTH = 128
_LCD_NATIVE_HEIGHT = 128

if LCD_1IN44 == 1:
	LCD_X = 2
	LCD_Y = 1
if LCD_1IN8 == 1:
	_LCD_NATIVE_WIDTH = 160
	_LCD_NATIVE_HEIGHT = 128
	LCD_X = 1
	LCD_Y = 2

try:
	_DISPLAY_PROFILE = get_display_profile()
	LCD_WIDTH, LCD_HEIGHT = _DISPLAY_PROFILE.size
except Exception:
	_DISPLAY_PROFILE = None
	LCD_WIDTH, LCD_HEIGHT = _LCD_NATIVE_WIDTH, _LCD_NATIVE_HEIGHT

LCD_X_MAXPIXEL = 132  #LCD width maximum memory 
LCD_Y_MAXPIXEL = 162  #LCD height maximum memory

# WebUI frame mirror (used by device_server.py)
# Support both KTOX and RaspyJack naming conventions
_FRAME_MIRROR_PATH = os.environ.get("KTOX_FRAME_PATH") or os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg")
_FRAME_MIRROR_ENABLED = (os.environ.get("KTOX_FRAME_MIRROR") or os.environ.get("RJ_FRAME_MIRROR", "1")) != "0"
try:
	_frame_fps = float(os.environ.get("KTOX_FRAME_FPS") or os.environ.get("RJ_FRAME_FPS", "10"))
	_FRAME_MIRROR_INTERVAL = 1.0 / max(1.0, _frame_fps)
except Exception:
	_FRAME_MIRROR_INTERVAL = 0.1
_last_frame_save = 0.0

# M5Cardputer frame streaming (optional optimization for 240x135 display)
# Support both KTOX and RaspyJack naming conventions
_M5_FRAME_ENABLED = (os.environ.get("KTOX_CARDPUTER_ENABLED") or os.environ.get("RJ_CARDPUTER_ENABLED", "1")) != "0"
_M5_FRAME_PATH = os.environ.get("KTOX_CARDPUTER_FRAME_PATH") or os.environ.get("RJ_CARDPUTER_FRAME_PATH", "/dev/shm/ktox_m5.jpg")
_M5_FRAME_WIDTH = int(os.environ.get("KTOX_CARDPUTER_FRAME_WIDTH") or os.environ.get("RJ_CARDPUTER_FRAME_WIDTH", "240"))
_M5_FRAME_HEIGHT = int(os.environ.get("KTOX_CARDPUTER_FRAME_HEIGHT") or os.environ.get("RJ_CARDPUTER_FRAME_HEIGHT", "135"))
_M5_FRAME_QUALITY = int(os.environ.get("KTOX_CARDPUTER_FRAME_QUALITY") or os.environ.get("RJ_CARDPUTER_FRAME_QUALITY", "75"))
_M5_FRAME_MODE = os.environ.get("KTOX_CARDPUTER_FRAME_MODE") or os.environ.get("RJ_CARDPUTER_FRAME_MODE", "contain")
_last_m5_frame_save = 0.0

# Screen rotation (degrees: 0, 90, 180, 270)
_SCREEN_ROTATION = 0

def _load_rotation_config():
	"""Load rotation setting from gui_conf.json."""
	global _SCREEN_ROTATION
	try:
		import json
		# Try to get config path from default module if available
		try:
			from default import config_file as conf_path
		except ImportError:
			# Fallback to common paths
			conf_path = None
			for path in [
				os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_conf.json"),
				"/root/KTOx/gui_conf.json",
			]:
				if os.path.isfile(path):
					conf_path = path
					break

		if conf_path and os.path.isfile(conf_path):
			with open(conf_path, 'r') as f:
				conf = json.load(f)
			_SCREEN_ROTATION = conf.get("UI", {}).get("ROTATION", 0)
	except Exception:
		_SCREEN_ROTATION = 0

def set_screen_rotation(degrees):
	"""Set screen rotation (0, 90, 180, 270)."""
	global _SCREEN_ROTATION
	if degrees in (0, 90, 180, 270):
		_SCREEN_ROTATION = degrees
		try:
			import json
			# Try to get config path from default module if available
			try:
				from default import config_file as conf_path
			except ImportError:
				# Fallback to common paths
				conf_path = None
				for path in [
					os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_conf.json"),
					"/root/KTOx/gui_conf.json",
				]:
					if os.path.isfile(path):
						conf_path = path
						break

			if conf_path and os.path.isfile(conf_path):
				with open(conf_path, 'r') as f:
					conf = json.load(f)
				conf.setdefault("UI", {})["ROTATION"] = degrees
				with open(conf_path, 'w') as f:
					json.dump(conf, f, indent=2)
		except Exception:
			pass

def _apply_rotation(pil_image, rotation):
	"""Apply rotation to PIL image if needed."""
	try:
		from PIL import Image
	except ImportError:
		return pil_image

	if rotation == 0:
		return pil_image
	elif rotation == 90:
		return pil_image.transpose(Image.ROTATE_270)
	elif rotation == 180:
		return pil_image.transpose(Image.ROTATE_180)
	elif rotation == 270:
		return pil_image.transpose(Image.ROTATE_90)
	return pil_image

# Load rotation on module import
_load_rotation_config()

#scanning method
L2R_U2D = 1
L2R_D2U = 2
R2L_U2D = 3
R2L_D2U = 4
U2D_L2R = 5
U2D_R2L = 6
D2U_L2R = 7
D2U_R2L = 8
SCAN_DIR_DFT = U2D_R2L


def _save_m5_frame(pil_image):
	"""Save M5Cardputer-optimized frame (240x135). Called from LCD_ShowImage."""
	if not _M5_FRAME_ENABLED:
		return
	try:
		from PIL import Image
		global _last_m5_frame_save
		now = time.monotonic()
		if (now - _last_m5_frame_save) < (1.0 / 30.0):
			return

		orig_w, orig_h = pil_image.size
		ratio_orig = orig_w / orig_h
		ratio_target = _M5_FRAME_WIDTH / _M5_FRAME_HEIGHT

		if _M5_FRAME_MODE == "stretch":
			scaled = pil_image.resize((_M5_FRAME_WIDTH, _M5_FRAME_HEIGHT), Image.LANCZOS)
		elif _M5_FRAME_MODE == "contain":
			thumb = pil_image.copy()
			thumb.thumbnail((_M5_FRAME_WIDTH, _M5_FRAME_HEIGHT), Image.LANCZOS)
			new_img = Image.new('RGB', (_M5_FRAME_WIDTH, _M5_FRAME_HEIGHT), (0, 0, 0))
			offset_x = (_M5_FRAME_WIDTH - thumb.width) // 2
			offset_y = (_M5_FRAME_HEIGHT - thumb.height) // 2
			new_img.paste(thumb, (offset_x, offset_y))
			scaled = new_img
		elif _M5_FRAME_MODE == "fit":
			if ratio_orig > ratio_target:
				new_w = int(orig_h * ratio_target)
				crop_img = pil_image.crop(((orig_w - new_w) // 2, 0, (orig_w + new_w) // 2, orig_h))
			else:
				new_h = int(orig_w / ratio_target)
				crop_img = pil_image.crop((0, (orig_h - new_h) // 2, orig_w, (orig_h + new_h) // 2))
			scaled = crop_img.resize((_M5_FRAME_WIDTH, _M5_FRAME_HEIGHT), Image.LANCZOS)
		else:
			scaled = pil_image.resize((_M5_FRAME_WIDTH, _M5_FRAME_HEIGHT), Image.LANCZOS)

		scaled.save(_M5_FRAME_PATH, "JPEG", quality=_M5_FRAME_QUALITY)
		_last_m5_frame_save = now
	except Exception:
		pass


class LCD:
	def __init__(self):
		# Public canvas dimensions track DISPLAY.type (128x128, 240x240,
		# 480x320, ...).  Keep native dimensions separately for the legacy
		# ST7735 SPI write path.
		self.width = LCD_WIDTH
		self.height = LCD_HEIGHT
		self._native_width = _LCD_NATIVE_WIDTH
		self._native_height = _LCD_NATIVE_HEIGHT
		self._profile = _DISPLAY_PROFILE
		self.LCD_Scan_Dir = SCAN_DIR_DFT
		self.LCD_X_Adjust = LCD_X
		self.LCD_Y_Adjust = LCD_Y

	"""    Hardware reset     """
	def  LCD_Reset(self):
		GPIO.output(LCD_Config.LCD_RST_PIN, GPIO.HIGH)
		LCD_Config.Driver_Delay_ms(100)
		GPIO.output(LCD_Config.LCD_RST_PIN, GPIO.LOW)
		LCD_Config.Driver_Delay_ms(100)
		GPIO.output(LCD_Config.LCD_RST_PIN, GPIO.HIGH)
		LCD_Config.Driver_Delay_ms(100)

	"""    Write register address and data     """
	def  LCD_WriteReg(self, Reg):
		GPIO.output(LCD_Config.LCD_DC_PIN, GPIO.LOW)
		LCD_Config.SPI_Write_Byte([Reg])

	def LCD_WriteData_8bit(self, Data):
		GPIO.output(LCD_Config.LCD_DC_PIN, GPIO.HIGH)
		LCD_Config.SPI_Write_Byte([Data])

	def LCD_WriteData_NLen16Bit(self, Data, DataLen):
		GPIO.output(LCD_Config.LCD_DC_PIN, GPIO.HIGH)
		for i in range(0, DataLen):
			LCD_Config.SPI_Write_Byte([Data >> 8])
			LCD_Config.SPI_Write_Byte([Data & 0xff])
		
	"""    Common register initialization    """
	def LCD_InitReg(self):
		#ST7735R Frame Rate
		self.LCD_WriteReg(0xB1)
		self.LCD_WriteData_8bit(0x01)
		self.LCD_WriteData_8bit(0x2C)
		self.LCD_WriteData_8bit(0x2D)

		self.LCD_WriteReg(0xB2)
		self.LCD_WriteData_8bit(0x01)
		self.LCD_WriteData_8bit(0x2C)
		self.LCD_WriteData_8bit(0x2D)

		self.LCD_WriteReg(0xB3)
		self.LCD_WriteData_8bit(0x01)
		self.LCD_WriteData_8bit(0x2C)
		self.LCD_WriteData_8bit(0x2D)
		self.LCD_WriteData_8bit(0x01)
		self.LCD_WriteData_8bit(0x2C)
		self.LCD_WriteData_8bit(0x2D)
		
		#Column inversion 
		self.LCD_WriteReg(0xB4)
		self.LCD_WriteData_8bit(0x07)
		
		#ST7735R Power Sequence
		self.LCD_WriteReg(0xC0)
		self.LCD_WriteData_8bit(0xA2)
		self.LCD_WriteData_8bit(0x02)
		self.LCD_WriteData_8bit(0x84)
		self.LCD_WriteReg(0xC1)
		self.LCD_WriteData_8bit(0xC5)

		self.LCD_WriteReg(0xC2)
		self.LCD_WriteData_8bit(0x0A)
		self.LCD_WriteData_8bit(0x00)

		self.LCD_WriteReg(0xC3)
		self.LCD_WriteData_8bit(0x8A)
		self.LCD_WriteData_8bit(0x2A)
		self.LCD_WriteReg(0xC4)
		self.LCD_WriteData_8bit(0x8A)
		self.LCD_WriteData_8bit(0xEE)
		
		self.LCD_WriteReg(0xC5)#VCOM 
		self.LCD_WriteData_8bit(0x0E)
		
		#ST7735R Gamma Sequence
		self.LCD_WriteReg(0xe0)
		self.LCD_WriteData_8bit(0x0f)
		self.LCD_WriteData_8bit(0x1a)
		self.LCD_WriteData_8bit(0x0f)
		self.LCD_WriteData_8bit(0x18)
		self.LCD_WriteData_8bit(0x2f)
		self.LCD_WriteData_8bit(0x28)
		self.LCD_WriteData_8bit(0x20)
		self.LCD_WriteData_8bit(0x22)
		self.LCD_WriteData_8bit(0x1f)
		self.LCD_WriteData_8bit(0x1b)
		self.LCD_WriteData_8bit(0x23)
		self.LCD_WriteData_8bit(0x37)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit(0x07)
		self.LCD_WriteData_8bit(0x02)
		self.LCD_WriteData_8bit(0x10)

		self.LCD_WriteReg(0xe1)
		self.LCD_WriteData_8bit(0x0f)
		self.LCD_WriteData_8bit(0x1b)
		self.LCD_WriteData_8bit(0x0f)
		self.LCD_WriteData_8bit(0x17)
		self.LCD_WriteData_8bit(0x33)
		self.LCD_WriteData_8bit(0x2c)
		self.LCD_WriteData_8bit(0x29)
		self.LCD_WriteData_8bit(0x2e)
		self.LCD_WriteData_8bit(0x30)
		self.LCD_WriteData_8bit(0x30)
		self.LCD_WriteData_8bit(0x39)
		self.LCD_WriteData_8bit(0x3f)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit(0x07)
		self.LCD_WriteData_8bit(0x03)
		self.LCD_WriteData_8bit(0x10) 
		
		#Enable test command
		self.LCD_WriteReg(0xF0)
		self.LCD_WriteData_8bit(0x01)
		
		#Disable ram power save mode
		self.LCD_WriteReg(0xF6)
		self.LCD_WriteData_8bit(0x00)
		
		#65k mode
		self.LCD_WriteReg(0x3A)
		self.LCD_WriteData_8bit(0x05)

	#********************************************************************************
	#function:	Set the display scan and color transfer modes
	#parameter: 
	#		Scan_dir   :   Scan direction
	#		Colorchose :   RGB or GBR color format
	#********************************************************************************
	def LCD_SetGramScanWay(self, Scan_dir):
		#Get the screen scan direction
		self.LCD_Scan_Dir = Scan_dir
		
		#Get GRAM and LCD width and height
		if (Scan_dir == L2R_U2D) or (Scan_dir == L2R_D2U) or (Scan_dir == R2L_U2D) or (Scan_dir == R2L_D2U) :
			self.width	= LCD_HEIGHT 
			self.height 	= LCD_WIDTH 
			if Scan_dir == L2R_U2D:
				MemoryAccessReg_Data = 0X00 | 0x00
			elif Scan_dir == L2R_D2U:
				MemoryAccessReg_Data = 0X00 | 0x80
			elif Scan_dir == R2L_U2D:
				MemoryAccessReg_Data = 0x40 | 0x00
			else:		#R2L_D2U:
				MemoryAccessReg_Data = 0x40 | 0x80
		else:
			self.width	= LCD_WIDTH 
			self.height 	= LCD_HEIGHT 
			if Scan_dir == U2D_L2R:
				MemoryAccessReg_Data = 0X00 | 0x00 | 0x20
			elif Scan_dir == U2D_R2L:
				MemoryAccessReg_Data = 0X00 | 0x40 | 0x20
			elif Scan_dir == D2U_L2R:
				MemoryAccessReg_Data = 0x80 | 0x00 | 0x20
			else:		#R2L_D2U
				MemoryAccessReg_Data = 0x40 | 0x80 | 0x20
		
		#please set (MemoryAccessReg_Data & 0x10) != 1
		if (MemoryAccessReg_Data & 0x10) != 1:
			self.LCD_X_Adjust = LCD_Y
			self.LCD_Y_Adjust = LCD_X
		else:
			self.LCD_X_Adjust = LCD_X
			self.LCD_Y_Adjust = LCD_Y
		
		# Set the read / write scan direction of the frame memory
		self.LCD_WriteReg(0x36)		#MX, MY, RGB mode 
		if LCD_1IN44 == 1:
			self.LCD_WriteData_8bit( MemoryAccessReg_Data | 0x08)	#0x08 set RGB
		else:
			self.LCD_WriteData_8bit( MemoryAccessReg_Data & 0xf7)	#RGB color filter panel

	#/********************************************************************************
	#function:	
	#			initialization
	#********************************************************************************/
	def LCD_Init(self, Lcd_ScanDir):
		if (LCD_Config.GPIO_Init() != 0):
			return -1
		
		#Turn on the backlight
		GPIO.output(LCD_Config.LCD_BL_PIN,GPIO.HIGH)
		
		#Hardware reset
		self.LCD_Reset()
		
		#Set the initialization register
		self.LCD_InitReg()
		
		#Set the display scan and color transfer modes	
		self.LCD_SetGramScanWay(Lcd_ScanDir)
		LCD_Config.Driver_Delay_ms(200)
		
		#sleep out
		self.LCD_WriteReg(0x11)
		LCD_Config.Driver_Delay_ms(120)
		
		#Turn on the LCD display
		self.LCD_WriteReg(0x29)
		
	#/********************************************************************************
	#function:	Sets the start position and size of the display area
	#parameter: 
	#	Xstart 	:   X direction Start coordinates
	#	Ystart  :   Y direction Start coordinates
	#	Xend    :   X direction end coordinates
	#	Yend    :   Y direction end coordinates
	#********************************************************************************/
	def LCD_SetWindows(self, Xstart, Ystart, Xend, Yend):
		#set the X coordinates
		self.LCD_WriteReg(0x2A)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit((Xstart & 0xff) + self.LCD_X_Adjust)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit(((Xend - 1) & 0xff) + self.LCD_X_Adjust)

		#set the Y coordinates
		self.LCD_WriteReg (0x2B)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit((Ystart & 0xff) + self.LCD_Y_Adjust)
		self.LCD_WriteData_8bit(0x00)
		self.LCD_WriteData_8bit(((Yend - 1) & 0xff )+ self.LCD_Y_Adjust)

		self.LCD_WriteReg(0x2C)

	def LCD_Clear(self):
		# Keep the legacy hardware clear bounded to the physical ST7735 RAM,
		# while public canvases may be larger for alternate display profiles.
		_buffer = [0xff]*(self._native_width * self._native_height * 2)
		self.LCD_SetWindows(0, 0, self._native_width, self._native_height)
		GPIO.output(LCD_Config.LCD_DC_PIN, GPIO.HIGH)
		for i in range(0,len(_buffer),4096):
			LCD_Config.SPI_Write_Byte(_buffer[i:i+4096])

	def LCD_ShowImage(self,Image,Xstart,Ystart):
		if (Image == None):
			return
		Image = _apply_rotation(Image, _SCREEN_ROTATION)
		imwidth, imheight = Image.size
		if imwidth != self.width or imheight != self.height:
			raise ValueError('Image must be same dimensions as display \
				({0}x{1}).' .format(self.width, self.height))

		# Preserve the active-profile frame for mirrors/streaming, then downsample
		# only for the legacy ST7735 SPI transport when the public canvas is larger.
		frame_image = Image
		hardware_image = Image
		if hardware_image.size != (self._native_width, self._native_height):
			resample = getattr(PILImage, "Resampling", PILImage).LANCZOS
			hardware_image = hardware_image.resize((self._native_width, self._native_height), resample)

		img = np.asarray(hardware_image)
		imheight, imwidth = img.shape[:2]
		pix = np.zeros((imheight, imwidth, 2), dtype = np.uint8)
		pix[...,[0]] = np.add(np.bitwise_and(img[...,[0]],0xF8),np.right_shift(img[...,[1]],5))
		pix[...,[1]] = np.add(np.bitwise_and(np.left_shift(img[...,[1]],3),0xE0),np.right_shift(img[...,[2]],3))
		# Use bytes directly - avoids slow Python list conversion on Pi Zero
		pix_bytes = pix.flatten().tobytes()
		self.LCD_SetWindows(0, 0, imwidth , imheight)
		GPIO.output(LCD_Config.LCD_DC_PIN, GPIO.HIGH)
		for i in range(0,len(pix_bytes),4096):
			LCD_Config.SPI_Write_Byte(pix_bytes[i:i+4096])
		# Mirror the LCD frame for WebUI (throttled)
		if _FRAME_MIRROR_ENABLED:
			global _last_frame_save
			try:
				now = time.monotonic()
				if (now - _last_frame_save) >= _FRAME_MIRROR_INTERVAL:
					frame_image.save(_FRAME_MIRROR_PATH, "JPEG", quality=80)
					_last_frame_save = now
			except Exception:
				pass
		# Save M5Cardputer-optimized frame if enabled
		_save_m5_frame(frame_image)
