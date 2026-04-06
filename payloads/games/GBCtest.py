#!/usr/bin/env python3
import os
import sys
import time
from pyboy import PyBoy # You'll need: pip install pyboy

# Standard KTOx Imports
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

def main():
    # 1. Setup Hardware
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    LCD_Config.GPIO_Init()
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    # 2. Load ROM
    rom_path = "/home/pi/ktox/roms/game.gbc"
    # 'dummy' window means it doesn't try to open a desktop window
    pyboy = PyBoy(rom_path, window_type="dummy") 
    
    try:
        while not pyboy.tick():
            # 3. Handle Inputs (KTOx Pins -> PyBoy)
            if GPIO.input(PINS["UP"]) == 0: pyboy.send_input(WindowEvent.PRESS_ARROW_UP)
            else: pyboy.send_input(WindowEvent.RELEASE_ARROW_UP)
            
            # (Add other buttons here following the same pattern)

            # 4. Refresh LCD
            # PyBoy gives us the screen buffer; we resize it to 128x128
            screen_image = pyboy.screen_image().resize((128, 128))
            lcd.LCD_ShowImage(screen_image, 0, 0)
            
            if GPIO.input(PINS["KEY3"]) == 0: # Exit
                break

    finally:
        pyboy.stop()
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
