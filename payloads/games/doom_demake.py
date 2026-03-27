#!/usr/bin/env python3
# doom_demake.py
# A DOOM-inspired raycasting game for the KTOx.
# Based on the DOOM-style-Game project, adapted for KTOx hardware.

import sys
import os
import time
import signal
import math
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont
import random

# --- Add KTOx root to Python path ---
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

# --- Hardware Imports ---
try:
    import LCD_Config
    import LCD_1in44
except ImportError:
    print("WARNING: LCD libraries not found. Running in simulation mode.")
    LCD_Config = None
    LCD_1in44 = None

# --- Settings ---
WIDTH, HEIGHT = 128, 128
RES = WIDTH, HEIGHT
HALF_WIDTH = WIDTH // 2
HALF_HEIGHT = HEIGHT // 2
FPS = 60 # Target FPS

PLAYER_POS = 1.5, 1.5
PLAYER_ANGLE = 0
PLAYER_SPEED = 0.004 * 30 # Adjusted for smaller scale
PLAYER_ROT_SPEED = 0.002 * 30 # Adjusted for smaller scale
PLAYER_SIZE_SCALE = 20
PLAYER_MAX_HEALTH = 100

FOV = math.pi / 3.0
HALF_FOV = FOV / 2
NUM_RAYS = WIDTH // 2
HALF_NUM_RAYS = NUM_RAYS // 2
DELTA_ANGLE = FOV / NUM_RAYS
MAX_DEPTH = 16

SCREEN_DIST = HALF_WIDTH / math.tan(HALF_FOV)
SCALE = WIDTH // NUM_RAYS

TEXTURE_SIZE = 64
HALF_TEXTURE_SIZE = TEXTURE_SIZE // 2
FLOOR_COLOR = (30, 30, 30)

# --- Map ---
text_map = [
    '################',
    '#.#............#',
    '#.#......#######',
    '#.#............#',
    '#..#...........#',
    '#..#...........#',
    '#..#...#.......#',
    '#......#.......#',
    '#......#.......#',
    '#......#.......#',
    '#..............#',
    '#..............#',
    '#......#.......#',
    '#......#.......#',
    '#######........#',
    '################',
]

world_map = {}
mini_map = set()
for j, row in enumerate(text_map):
    for i, char in enumerate(row):
        if char != '.':
            mini_map.add((i, j))
            world_map[(i, j)] = 1

# --- RayCasting ---
class RayCasting:
    def __init__(self, game):
        self.game = game
        self.ray_casting_result = []
        self.objects_to_render = []
        self.textures = self.game.object_renderer.wall_textures

    def get_objects_to_render(self):
        self.objects_to_render = []
        for ray, values in enumerate(self.ray_casting_result):
            depth, proj_height, texture, offset = values
            if proj_height < HEIGHT:
                shade = max(0.2, 1.0 - (depth / MAX_DEPTH))
                tex_x = int(offset * (TEXTURE_SIZE - SCALE))
                wall_column = self.textures[texture].crop((tex_x, 0, tex_x + SCALE, TEXTURE_SIZE))
                wall_column = wall_column.resize((SCALE, proj_height), Image.NEAREST)
                if shade < 1.0:
                    wall_column = wall_column.point(lambda p: p * shade)
                wall_pos = (ray * SCALE, HALF_HEIGHT - proj_height // 2)
                self.objects_to_render.append((depth, wall_column, wall_pos))
        
        for sprite in self.game.object_handler.sprite_list:
            self.objects_to_render.append(sprite.object_locate(self.game.player))

    def ray_cast(self):
        self.ray_casting_result = []
        ox, oy = self.game.player.pos
        x_map, y_map = self.game.player.map_pos

        ray_angle = self.game.player.angle - HALF_FOV + 0.0001
        for ray in range(NUM_RAYS):
            sin_a = math.sin(ray_angle)
            cos_a = math.cos(ray_angle)

            # horizontals
            y_hor, dy = (y_map + 1, 1) if sin_a > 0 else (y_map - 1e-6, -1)
            depth_hor = (y_hor - oy) / (sin_a + 1e-6)
            x_hor = ox + depth_hor * cos_a
            delta_depth = dy / (sin_a + 1e-6)
            dx = delta_depth * cos_a

            for i in range(MAX_DEPTH):
                tile_hor = int(x_hor), int(y_hor)
                if tile_hor in self.game.map.world_map:
                    texture_hor = self.game.map.world_map[tile_hor]
                    break
                x_hor += dx
                y_hor += dy
                depth_hor += delta_depth

            # verticals
            x_vert, dx = (x_map + 1, 1) if cos_a > 0 else (x_map - 1e-6, -1)
            depth_vert = (x_vert - ox) / (cos_a + 1e-6)
            y_vert = oy + depth_vert * sin_a
            delta_depth = dx / (cos_a + 1e-6)
            dy = delta_depth * sin_a

            for i in range(MAX_DEPTH):
                tile_vert = int(x_vert), int(y_vert)
                if tile_vert in self.game.map.world_map:
                    texture_vert = self.game.map.world_map[tile_vert]
                    break
                x_vert += dx
                y_vert += dy
                depth_vert += delta_depth

            if depth_vert < depth_hor:
                depth, texture = depth_vert, texture_vert
                y_vert %= 1
                offset = y_vert if cos_a > 0 else (1 - y_vert)
            else:
                depth, texture = depth_hor, texture_hor
                x_hor %= 1
                offset = x_hor if sin_a > 0 else (1 - x_hor)

            depth *= math.cos(self.game.player.angle - ray_angle)
            proj_height = min(int(SCREEN_DIST / (depth + 0.0001)), HEIGHT*2)
            self.ray_casting_result.append((depth, proj_height, texture, offset))
            ray_angle += DELTA_ANGLE

    def update(self):
        self.ray_cast()
        self.get_objects_to_render()

# --- Player ---
class Player:
    def __init__(self, game):
        self.game = game
        self.x, self.y = PLAYER_POS
        self.angle = PLAYER_ANGLE
        self.health = PLAYER_MAX_HEALTH

    def movement(self):
        sin_a = math.sin(self.angle)
        cos_a = math.cos(self.angle)
        dx, dy = 0, 0
        speed = PLAYER_SPEED * self.game.delta_time
        speed_sin = speed * sin_a
        speed_cos = speed * cos_a

        keys = self.game.keys
        if keys['UP']:
            dx += speed_cos
            dy += speed_sin
        if keys['DOWN']:
            dx -= speed_cos
            dy -= speed_sin
        
        self.check_wall_collision(dx, dy)

        if keys['LEFT']:
            self.angle -= PLAYER_ROT_SPEED * self.game.delta_time
        if keys['RIGHT']:
            self.angle += PLAYER_ROT_SPEED * self.game.delta_time
        self.angle %= (2 * math.pi)

    def check_wall(self, x, y):
        return (x, y) not in self.game.map.world_map

    def check_wall_collision(self, dx, dy):
        new_x = self.x + dx
        new_y = self.y + dy
        
        # Check collision with sliding
        if self.check_wall(int(new_x), int(self.y)):
            self.x = new_x
        if self.check_wall(int(self.x), int(new_y)):
            self.y = new_y

    def draw(self):
        self.game.screen_draw.line(
            (self.x * 10, self.y * 10),
            (self.x * 10 + WIDTH * math.cos(self.angle), self.y * 10 + WIDTH * math.sin(self.angle)),
            'yellow', width=2
        )
        self.game.screen_draw.ellipse(
            (self.x * 10 - 5, self.y * 10 - 5, self.x * 10 + 5, self.y * 10 + 5),
            fill='green', outline='green'
        )

    def update(self):
        self.movement()

    @property
    def pos(self):
        return self.x, self.y

    @property
    def map_pos(self):
        return int(self.x), int(self.y)

# --- SpriteObject ---
class SpriteObject:
    def __init__(self, game, path, pos=(10.5, 3.5), scale=0.7, shift=0.27):
        self.game = game
        self.player = game.player
        self.x, self.y = pos
        self.image = self.get_image(path)
        self.SPRITE_SCALE = scale
        self.SPRITE_HEIGHT_SHIFT = shift
        self.is_dead = False
        self.health = 100
        self.attack_damage = 10
        self.attack_cooldown = 0
        self.speed = 0.02
        self.chasing = False

    def get_image(self, path):
        # In KTOx, we create images procedurally
        if "cacodemon" in path:
            img = Image.new("RGBA", (TEXTURE_SIZE, TEXTURE_SIZE), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # Body
            d.ellipse([(4, 10), (TEXTURE_SIZE-4, TEXTURE_SIZE-4)], fill=(180, 20, 20), outline=(100, 10, 10), width=2)
            # Horns
            d.polygon([(10, 12), (5, 2), (20, 8)], fill=(200, 200, 200))
            d.polygon([(TEXTURE_SIZE-10, 12), (TEXTURE_SIZE-5, 2), (TEXTURE_SIZE-20, 8)], fill=(200, 200, 200))
            # Eye
            eye_box = (TEXTURE_SIZE*0.4, TEXTURE_SIZE*0.35)
            eye_size = (TEXTURE_SIZE*0.6, TEXTURE_SIZE*0.55)
            d.ellipse([eye_box, eye_size], fill=(255, 255, 100))
            d.ellipse([(TEXTURE_SIZE*0.45, TEXTURE_SIZE*0.4), (TEXTURE_SIZE*0.55, TEXTURE_SIZE*0.5)], fill="red")
            # Mouth
            d.arc([(20, 50), (TEXTURE_SIZE-20, TEXTURE_SIZE-15)], 20, 160, fill=(100, 10, 10), width=3)
            return img

    def object_locate(self, player):
        if self.is_dead:
            return (False, None, None)
        
        if self.health <= 0:
            self.is_dead = True
            # Could add a death animation trigger here later
            return (False, None, None)

        dx, dy = self.x - player.x, self.y - player.y
        self.dist = math.sqrt(dx ** 2 + dy ** 2)

        self.theta = math.atan2(dy, dx)
        gamma = self.theta - player.angle
        if dx > 0 and 180 <= math.degrees(player.angle) <= 360 or dx < 0 and dy < 0:
            gamma += (2 * math.pi)

        delta_rays = int(gamma / DELTA_ANGLE)
        self.screen_x = (HALF_NUM_RAYS + delta_rays) * SCALE

        # self.dist *= math.cos(HALF_FOV - self.screen_x / (2*HALF_WIDTH) * FOV) # Incorrect fisheye correction
        
        if 0 <= self.screen_x <= WIDTH and self.dist > 0.5:
            proj_height = min(int(SCREEN_DIST / (self.dist + 1e-6) * self.SPRITE_SCALE), HEIGHT*2)
            half_proj_height = proj_height // 2
            shift = proj_height * self.SPRITE_HEIGHT_SHIFT

            sprite_pos = (int(self.screen_x - half_proj_height), int(HALF_HEIGHT - half_proj_height + shift))
            sprite = self.image.resize((proj_height, proj_height), Image.NEAREST)
            
            shade = max(0.3, 1.0 - (self.dist / (MAX_DEPTH * 0.7)))
            if shade < 1.0:
                sprite = sprite.point(lambda p: p * shade)

            return (self.dist, sprite, sprite_pos)
        else:
            return (False, None, None)

    def update(self):
        if self.is_dead:
            return

        if self.attack_cooldown > 0:
            self.attack_cooldown -= self.game.delta_time

        # Basic AI
        dist_to_player = math.sqrt((self.player.x - self.x) ** 2 + (self.player.y - self.y) ** 2)

        if dist_to_player > 20: # Too far away
            self.chasing = False
        elif dist_to_player < 1.0: # Close enough to attack
            self.chasing = False
            if self.attack_cooldown <= 0:
                self.attack_cooldown = 1.0 # 1 second cooldown
                self.game.player.health -= self.attack_damage
                self.game.pain_timer = 0.2 # Trigger pain flash
        else: # Chase
            self.chasing = True
            
        if self.chasing:
            dx = self.player.x - self.x
            dy = self.player.y - self.y
            # Normalize
            dist = dist_to_player
            dx /= dist
            dy /= dist
            # Move
            new_x = self.x + dx * self.speed
            new_y = self.y + dy * self.speed
            # Check wall collision for sprite
            if self.game.map.check_wall(int(new_x), int(self.y)):
                self.x = new_x
            if self.game.map.check_wall(int(self.x), int(new_y)):
                self.y = new_y


# --- ObjectHandler ---
class ObjectHandler:
    def update(self):
        for sprite in self.sprite_list:
            sprite.update()

    def add_sprite(self, sprite):
        self.sprite_list.append(sprite)

# --- ObjectRenderer ---
class ObjectRenderer:
    def __init__(self, game):
        self.game = game
        self.screen = game.screen
        self.wall_textures = self.load_wall_textures()

    def draw(self):
        self.draw_background()
        self.render_game_objects()

    def draw_background(self):
        # Ceiling gradient
        for y in range(HALF_HEIGHT):
            shade = 1.0 - (y / HALF_HEIGHT)
            color = (int(20 * shade), int(20 * shade), int(30 * shade))
            self.game.screen_draw.line([(0, y), (WIDTH, y)], fill=color)
            
        # Floor gradient
        for y in range(HALF_HEIGHT, HEIGHT):
            shade = (y - HALF_HEIGHT) / HALF_HEIGHT
            color = (int(40 * shade), int(30 * shade), int(25 * shade))
            self.game.screen_draw.line([(0, y), (WIDTH, y)], fill=color)

    def render_game_objects(self):
        list_objects = sorted(self.game.raycasting.objects_to_render, key=lambda t: t[0], reverse=True)
        for depth, image, pos in list_objects:
            if image and pos:
                # Defensive cast to int to solve the persistent TypeError
                int_pos = (int(pos[0]), int(pos[1]))
                self.screen.paste(image, int_pos, image)

    @staticmethod
    def get_stone_texture(res=(TEXTURE_SIZE, TEXTURE_SIZE)):
        """Generates a procedural stone brick texture."""
        img = Image.new('RGB', res, (50, 50, 50))
        draw = ImageDraw.Draw(img)
        for x in range(0, res[0], 32): # Vertical mortar
            draw.line([(x, 0), (x, res[1])], fill=(40, 40, 40), width=2)
        for y in range(0, res[1], 16): # Horizontal mortar
            draw.line([(0, y), (res[0], y)], fill=(40, 40, 40), width=2)
            for x_offset in range(0, res[0], 32):
                if (y // 16) % 2 == 0:
                    draw.line([(x_offset + 16, y), (x_offset + 16, y + 16)], fill=(40, 40, 40), width=2)
        # Add some grime
        for _ in range(res[0] * res[1] // 10):
            x, y = random.randint(0, res[0]-1), random.randint(0, res[1]-1)
            c = random.randint(45, 55)
            draw.point((x, y), fill=(c, c, c))
        return img

    @staticmethod
    def get_metal_texture(res=(TEXTURE_SIZE, TEXTURE_SIZE)):
        """Generates a procedural metal panel texture."""
        img = Image.new('RGB', res, (80, 80, 80))
        draw = ImageDraw.Draw(img)
        # Panel lines
        draw.line([(0, 0), (res[0], 0)], fill=(60, 60, 60), width=2)
        draw.line([(0, 0), (0, res[1])], fill=(60, 60, 60), width=2)
        draw.line([(res[0]-1, 0), (res[0]-1, res[1])], fill=(100, 100, 100), width=2)
        draw.line([(0, res[1]-1), (res[0], res[1]-1)], fill=(100, 100, 100), width=2)
        # Rivets
        for x in [5, res[0] - 7]:
            for y in [5, res[1] - 7]:
                draw.rectangle([(x, y), (x+2, y+2)], fill=(65, 65, 65))
                draw.point((x+1, y+1), fill=(95, 95, 95))
        # Rust/grime
        for _ in range(res[0] * res[1] // 20):
            x, y = random.randint(0, res[0]-1), random.randint(0, res[1]-1)
            c = random.randint(70, 75)
            draw.point((x, y), fill=(c, c-5, c-10))
        return img

    def load_wall_textures(self):
        return {
            1: self.get_stone_texture(),
            2: self.get_metal_texture(),
        }

# --- Map ---
class Map:
    def __init__(self, game):
        self.game = game
        self.mini_map = mini_map
        self.world_map = world_map
        self.rows = len(text_map)
        self.cols = len(text_map[0])

    def draw(self):
        [self.game.screen_draw.rectangle((pos[0] * 10, pos[1] * 10, pos[0] * 10 + 10, pos[1] * 10 + 10),
                                         fill='darkgray', outline='darkgray')
         for pos in self.mini_map]

# --- Weapon ---
class Weapon:
    def __init__(self, game, path='weapon/shotgun/0.png', scale=0.4, animation_time=90):
        self.game = game
        self.scale = scale
        self.image = self.get_image(path)
        self.animation_time = animation_time
        self.reloading = False
        self.num_images = 1 # Simplified
        self.frame_counter = 0
        self.damage = 50

    def get_image(self, path):
        # Procedural weapon sprite (shotgun style)
        img = Image.new("RGBA", (150, 150), (0,0,0,0))
        d = ImageDraw.Draw(img)
        # Barrel
        d.rectangle([(65, 50), (85, 100)], fill=(60, 60, 60))
        d.rectangle([(68, 52), (82, 95)], fill=(50, 50, 50))
        d.ellipse([(70, 40), (80, 50)], fill=(40,40,40))
        # Pump
        d.rectangle([(60, 100), (90, 115)], fill=(100, 80, 60))
        # Stock/Body
        d.rectangle([(50, 115), (100, 130)], fill=(70, 70, 70))
        # Handle
        d.polygon([(100, 115), (110, 135), (95, 145), (85, 130)], fill=(90, 70, 50))
        return img

    def animate_shot(self):
        if self.reloading:
            self.game.player.shot = False
            if False: # self.animation_trigger was not defined
                self.frame_counter += 1
                if self.frame_counter == self.num_images:
                    self.reloading = False
                    self.frame_counter = 0

    def draw(self):
        # Recoil animation
        recoil_progress = max(0, self.game.shoot_cooldown / 0.5) # Cooldown is 0.5s
        recoil_offset = int((-(recoil_progress**2) + recoil_progress) * 4 * 20) # Parabolic arc for smooth recoil
        weapon_pos = (HALF_WIDTH - self.image.width // 2, HEIGHT - self.image.height + 10 - recoil_offset)
        self.game.screen.paste(self.image, weapon_pos, self.image)

        # Muzzle flash
        if self.game.muzzle_flash_timer > 0:
            flash_size = int(WIDTH * 0.4)
            half_flash = flash_size // 2
            flash_points = [
                (HALF_WIDTH - half_flash, HALF_HEIGHT), (HALF_WIDTH + half_flash, HALF_HEIGHT),
                (HALF_WIDTH, HALF_HEIGHT - half_flash), (HALF_WIDTH, HALF_HEIGHT + half_flash),
                (HALF_WIDTH - int(half_flash*0.7), HALF_HEIGHT - int(half_flash*0.7)),
                (HALF_WIDTH + int(half_flash*0.7), HALF_HEIGHT - int(half_flash*0.7)),
                (HALF_WIDTH - int(half_flash*0.7), HALF_HEIGHT + int(half_flash*0.7)),
                (HALF_WIDTH + int(half_flash*0.7), HALF_HEIGHT + int(half_flash*0.7)),
            ]
            # Draw a bright, semi-random star shape
            random.shuffle(flash_points)
            for i in range(0, len(flash_points), 2):
                self.game.screen_draw.line([flash_points[i], flash_points[i-1]], fill=(255, 255, random.randint(0, 255)), width=2)

    def update(self):
        pass # Simplified

# --- Main Game Class ---
class Game:
    def __init__(self):
        self.keys = {
            "UP": False, "DOWN": False, "LEFT": False, "RIGHT": False,
            "KEY1": False, "KEY2": False, "KEY3": False
        }
        self.screen = Image.new("RGB", (WIDTH, HEIGHT), "black")
        self.screen_draw = ImageDraw.Draw(self.screen)
        self.clock = time.time()
        self.delta_time = 1
        self.running = True
        self.shoot_cooldown = 0
        self.muzzle_flash_timer = 0
        self.pain_timer = 0
        self.init_hardware()
        self.new_game()

    def init_hardware(self):
        if LCD_1in44:
            self.LCD = LCD_1in44.LCD()
            self.LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            self.LCD.LCD_Clear()
            GPIO.setmode(GPIO.BCM)
            self.PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
            for pin in self.PINS.values():
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        else:
            self.LCD = None # Simulation mode
            print("Running in simulation mode. No hardware initialized.")

    def new_game(self):
        self.map = Map(self)
        self.player = Player(self)
        self.object_renderer = ObjectRenderer(self)
        self.raycasting = RayCasting(self)
        self.object_handler = ObjectHandler(self)
        self.weapon = Weapon(self)

    def update(self):
        if self.shoot_cooldown > 0:
            self.shoot_cooldown -= self.delta_time
        if self.muzzle_flash_timer > 0:
            self.muzzle_flash_timer -= self.delta_time
        if self.pain_timer > 0:
            self.pain_timer -= self.delta_time
        self.player.update()
        self.raycasting.update()
        self.object_handler.update()
        self.weapon.update()
        
        now = time.time()
        self.delta_time = now - self.clock
        self.clock = now
        
        # Cap FPS
        sleep_time = (1.0 / FPS) - self.delta_time
        if sleep_time > 0:
            time.sleep(sleep_time)

    def draw(self):
        self.object_renderer.draw()
        self.weapon.draw()
        # self.map.draw() # Mini-map disabled for performance
        # self.player.draw()

        # Pain flash
        if self.pain_timer > 0:
            # Create a red, semi-transparent overlay
            overlay = Image.new('RGBA', (WIDTH, HEIGHT), (255, 0, 0, 50))
            self.screen.paste(overlay, (0,0), overlay)

        self.draw_hud()

    def draw_hud(self):
        """Draws the Heads-Up Display."""
        bar_height = 20
        self.game.screen_draw.rectangle([(0, HEIGHT - bar_height), (WIDTH, HEIGHT)], fill=(50, 50, 50))
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except IOError:
            font = ImageFont.load_default()
        
        health_text = f"HEALTH: {max(0, self.player.health)}%"
        self.game.screen_draw.text((5, HEIGHT - bar_height + 2), health_text, font=font, fill=(255, 255, 0))


    def check_events(self):
        if self.LCD:
            self.keys['UP'] = GPIO.input(self.PINS['UP']) == 0
            self.keys['DOWN'] = GPIO.input(self.PINS['DOWN']) == 0
            self.keys['LEFT'] = GPIO.input(self.PINS['LEFT']) == 0
            self.keys['RIGHT'] = GPIO.input(self.PINS['RIGHT']) == 0
            self.keys['KEY1'] = GPIO.input(self.PINS['KEY1']) == 0
            self.keys['KEY2'] = GPIO.input(self.PINS['KEY2']) == 0
            if GPIO.input(self.PINS['KEY3']) == 0:
                self.running = False
        else: # Simulation keys
            # In a real sim, you'd poll a library like pynput
            pass

        if self.keys['KEY1'] and self.shoot_cooldown <= 0: # Shoot
            self.shoot_cooldown = 0.5 # 500ms cooldown
            self.muzzle_flash_timer = 0.1 # 100ms flash
            for sprite in self.object_handler.sprite_list:
                sprite.dist = math.sqrt((self.player.x - sprite.x) ** 2 + (self.player.y - sprite.y) ** 2)

            for sprite in sorted(self.object_handler.sprite_list, key=lambda s: s.dist):
                if not sprite.is_dead:
                    dx, dy = sprite.x - self.player.x, sprite.y - self.player.y
                    dist = sprite.dist
                    if dist > 0:
                        norm_dx, norm_dy = dx / dist, dy / dist
                        dot_product = (norm_dx * math.sin(self.player.angle) + norm_dy * math.cos(self.player.angle))
                        if dot_product > 0.95: # Narrow cone of fire
                            sprite.health -= self.weapon.damage
                            break


    def run(self):
        while self.running:
            self.check_events()
            self.update()
            self.draw()
            if self.LCD:
                self.LCD.LCD_ShowImage(self.screen, 0, 0)

    def cleanup(self):
        """Handles cleaning up GPIO and LCD."""
        if hasattr(self, 'LCD') and self.LCD:
            self.LCD.LCD_Clear()
        if LCD_1in44: # Check if hardware library was imported
            GPIO.cleanup()
        print("DOOM Demake: Cleanup complete.")

if __name__ == '__main__':
    game = Game()
    
    def cleanup_handler(signum, frame):
        game.running = False
    
    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    try:
        game.run()
    except Exception as e:
        with open("/tmp/doom_demake_error.log", "w") as f:
            f.write(f"An error occurred: {e}\n")
            import traceback
            traceback.print_exc(file=f)
        print(f"An error occurred: {e}. See /home/null/testing/doom_demake_error.log")
    finally:
        game.cleanup()
        print("DOOM Demake: Exiting.")
        sys.exit(0)