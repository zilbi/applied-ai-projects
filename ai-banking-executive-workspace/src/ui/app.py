from pathlib import Path

import pygame

from src.auth import create_user
from src.db import init_db
from src import repositories
from src.ui.screens import UIRenderer
from src.ui.state import AppState
from src.ui.theme import COLORS, FONT_NAME, FONT_SIZES, FPS, HEIGHT, WIDTH


LOADING_BACKGROUND_PATH = Path(__file__).resolve().parents[2] / "assets" / "loading_background.png"


class SponsorAssistantApp:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("AI-Powered Banking Executive Workspace")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self._draw_loading_screen("Preparing the portfolio workspace", 0.38)
        init_db()
        self._draw_loading_screen("Loading portfolio data and access controls", 0.76)
        self._ensure_demo_profile()
        self.clock = pygame.time.Clock()
        self.state = AppState()
        self.state.current_user = self._demo_user()
        self.state.focused_input_key = None
        self.state.login_error = ""
        self.fonts = {
            "small": pygame.font.SysFont(FONT_NAME, FONT_SIZES["small"]),
            "normal": pygame.font.SysFont(FONT_NAME, FONT_SIZES["normal"]),
            "subtitle": pygame.font.SysFont(FONT_NAME, FONT_SIZES["subtitle"], bold=True),
            "title": pygame.font.SysFont(FONT_NAME, FONT_SIZES["title"], bold=True),
        }
        self.renderer = UIRenderer(self.state, self.fonts)

    def _draw_loading_screen(self, status, progress):
        if LOADING_BACKGROUND_PATH.exists():
            background = pygame.image.load(str(LOADING_BACKGROUND_PATH)).convert()
            background = pygame.transform.smoothscale(background, (WIDTH, HEIGHT))
            self.screen.blit(background, (0, 0))
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((255, 255, 255, 74))
            self.screen.blit(overlay, (0, 0))
        else:
            self.screen.fill(COLORS["background"])
        title_font = pygame.font.SysFont(FONT_NAME, 30, bold=True)
        text_font = pygame.font.SysFont(FONT_NAME, FONT_SIZES["normal"])
        brand_font = pygame.font.SysFont(FONT_NAME, 22, bold=True)
        card = pygame.Rect(WIDTH // 2 - 260, HEIGHT // 2 - 128, 520, 256)
        pygame.draw.rect(self.screen, COLORS["surface"], card, border_radius=16)
        pygame.draw.rect(self.screen, COLORS["border"], card, width=1, border_radius=16)
        logo_center = (card.centerx, card.y + 58)
        pygame.draw.circle(self.screen, (33, 160, 56), logo_center, 26)
        pygame.draw.arc(self.screen, (15, 168, 224), pygame.Rect(logo_center[0] - 26, logo_center[1] - 26, 52, 52), 1.65, 4.95, 5)
        pygame.draw.line(self.screen, COLORS["surface"], (logo_center[0] - 12, logo_center[1] + 1), (logo_center[0] - 3, logo_center[1] + 10), 4)
        pygame.draw.line(self.screen, COLORS["surface"], (logo_center[0] - 3, logo_center[1] + 10), (logo_center[0] + 14, logo_center[1] - 10), 4)
        brand = brand_font.render("PORTFOLIO AI", True, COLORS["primary_dark"])
        self.screen.blit(brand, brand.get_rect(center=(card.centerx, card.y + 98)))
        title = title_font.render("AI-Powered Banking Executive Workspace", True, COLORS["text"])
        self.screen.blit(title, title.get_rect(center=(card.centerx, card.y + 138)))
        track = pygame.Rect(card.x + 72, card.y + 174, card.width - 144, 10)
        pygame.draw.rect(self.screen, COLORS["surface_alt"], track, border_radius=5)
        pygame.draw.rect(self.screen, COLORS["primary"], pygame.Rect(track.x, track.y, int(track.width * progress), track.height), border_radius=5)
        label = text_font.render(status, True, COLORS["muted"])
        self.screen.blit(label, label.get_rect(center=(card.centerx, card.y + 212)))
        pygame.event.pump()
        pygame.display.flip()

    def _demo_user(self):
        user = repositories.get_user_by_login("admin") or repositories.get_user_by_login("sponsor")
        if user:
            return user
        return create_user("admin", "admin", "Администратор системы", "admin")

    def _ensure_demo_profile(self):
        user = repositories.get_user_by_login("admin")
        if user:
            repositories.ensure_client_demo_profile(user)

    def run(self):
        while self.state.running:
            self._handle_events()
            self._draw()
            pygame.display.flip()
            self.clock.tick(FPS)
        pygame.quit()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.state.running = False
            else:
                self.renderer.handle_event(event)

    def _draw(self):
        self.screen.fill(COLORS["background"])
        self.renderer.draw(self.screen)
