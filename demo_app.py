"""Demo application for cjm-transcript-vad-align library.

Demonstrates VAD chunk alignment with card stack navigation, audio playback,
and keyboard navigation. Works standalone without the full transcript workflow.

Run with: python demo_app.py
"""

from typing import List, Dict, Any, Callable, Tuple
from pathlib import Path
import tempfile

from fasthtml.common import (
    fast_app, Div, H1, P, Span, Button, Input, Script, Audio,
    APIRouter, Details, Summary, FileResponse,
)

# Plugin system
from cjm_plugin_system.core.manager import PluginManager
from cjm_plugin_system.core.scheduling import SafetyScheduler

# DaisyUI components
from cjm_fasthtml_daisyui.core.resources import get_daisyui_headers
from cjm_fasthtml_daisyui.core.testing import create_theme_persistence_script
from cjm_fasthtml_daisyui.components.data_display.badge import badge, badge_styles, badge_sizes
from cjm_fasthtml_daisyui.components.data_display.collapse import (
    collapse, collapse_title, collapse_content, collapse_modifiers
)
from cjm_fasthtml_daisyui.utilities.semantic_colors import bg_dui, text_dui

# Tailwind utilities
from cjm_fasthtml_tailwind.utilities.spacing import p, m
from cjm_fasthtml_tailwind.utilities.sizing import w, h, min_h, container, max_w
from cjm_fasthtml_tailwind.utilities.typography import font_size, font_weight, text_align, uppercase, tracking
from cjm_fasthtml_tailwind.utilities.layout import overflow
from cjm_fasthtml_tailwind.utilities.effects import ring
from cjm_fasthtml_tailwind.utilities.transitions_and_animation import transition, duration
from cjm_fasthtml_tailwind.utilities.flexbox_and_grid import (
    flex_display, flex_direction, justify, items, gap, grow
)
from cjm_fasthtml_tailwind.core.base import combine_classes

# App core
from cjm_fasthtml_app_core.core.routing import register_routes
from cjm_fasthtml_app_core.core.htmx import handle_htmx_request

# Design system recipes (V10 panel / chrome variants)
from cjm_fasthtml_design_system.panels import panels
from cjm_fasthtml_design_system.chrome import chrome
from cjm_fasthtml_design_system.text_tiers import text_tiers

# Interactions library
from cjm_fasthtml_interactions.core.state_store import get_session_id

# State store
from cjm_workflow_state.state_store import SQLiteWorkflowStateStore

# Keyboard navigation
from cjm_fasthtml_keyboard_navigation.core.manager import ZoneManager
from cjm_fasthtml_keyboard_navigation.components.system import render_keyboard_system
from cjm_fasthtml_keyboard_navigation.components.hints import render_keyboard_hints

# Card stack library
from cjm_fasthtml_card_stack.keyboard.actions import build_card_stack_url_map
from cjm_fasthtml_card_stack.components.settings_modal import render_card_stack_settings_modal
from cjm_fasthtml_card_stack.core.constants import DEFAULT_VISIBLE_COUNT, DEFAULT_CARD_WIDTH

# Alignment library imports
from cjm_transcript_vad_align.models import VADChunk, AlignmentUrls
from cjm_transcript_vad_align.services.alignment import AlignmentService
from cjm_transcript_vad_align.html_ids import AlignmentHtmlIds
from cjm_transcript_vad_align.components.card_stack_config import (
    ALIGN_CS_CONFIG, ALIGN_CS_IDS, ALIGN_CS_BTN_IDS,
)
from cjm_transcript_vad_align.components.keyboard_config import create_align_kb_parts
from cjm_transcript_vad_align.components.step_renderer import (
    render_align_column_body, render_align_toolbar,
    render_align_footer_content, render_align_mini_stats_text,
)
from cjm_transcript_vad_align.routes.init import init_alignment_routers
from cjm_transcript_vad_align.routes.handlers import AlignInitResult, _handle_align_init

# Web Audio library — static asset mount (SoundTouch worklet for pitch-preserving speed)
from cjm_fasthtml_web_audio.components import mount_web_audio_static


# =============================================================================
# Test Audio Files
# =============================================================================

SEGMENTS_DIR = Path(__file__).parent / "test_files" / "segments_vad"

# Use first 3 segments for quick VAD analysis in demo
TEST_AUDIO_PATHS = sorted(SEGMENTS_DIR.glob("*.mp3"))[:3] if SEGMENTS_DIR.exists() else []


# =============================================================================
# Demo HTML IDs
# =============================================================================

class DemoHtmlIds:
    """HTML IDs for demo app layout."""
    CONTAINER = "align-demo-container"
    COLUMN = "align-demo-column"
    COLUMN_HEADER = "align-demo-column-header"
    COLUMN_CONTENT = "align-demo-column-content"
    MINI_STATS = "align-demo-mini-stats"
    KEYBOARD_SYSTEM = "align-demo-kb-system"
    SHARED_HINTS = "align-demo-hints"
    SHARED_TOOLBAR = "align-demo-toolbar"
    SHARED_FOOTER = "align-demo-footer"
    SETTINGS_MODAL = "align-demo-settings-modal"


# =============================================================================
# Single-Zone Keyboard System
# =============================================================================

def build_single_zone_kb_system(
    urls: AlignmentUrls,
) -> Tuple[ZoneManager, Any]:
    """Build single-zone keyboard system for alignment only."""
    # Get alignment-specific building blocks
    align_zone, align_actions, align_modes = create_align_kb_parts(
        ids=ALIGN_CS_IDS,
        button_ids=ALIGN_CS_BTN_IDS,
        config=ALIGN_CS_CONFIG,
    )

    # Assemble into ZoneManager (single zone, no zone switching)
    kb_manager = ZoneManager(
        zones=(align_zone,),
        actions=align_actions,
        modes=align_modes,
        initial_zone_id=align_zone.id,
        state_hidden_inputs=True,
    )

    # Build URL maps
    # Include only the card stack focused index input
    include_selector = f"#{ALIGN_CS_IDS.focused_index_input}"

    # URL mappings (card stack navigation only)
    url_map = build_card_stack_url_map(ALIGN_CS_BTN_IDS, urls.card_stack)

    # Target maps
    target = f"#{ALIGN_CS_IDS.card_stack}"
    target_map = {btn_id: target for btn_id in url_map}

    # Include maps
    include_map = {btn_id: include_selector for btn_id in url_map}

    # Swap map (none for all - OOB swaps handle updates)
    swap_map = {btn_id: "none" for btn_id in url_map}

    kb_system = render_keyboard_system(
        kb_manager,
        url_map=url_map,
        target_map=target_map,
        include_map=include_map,
        swap_map=swap_map,
        show_hints=False,
        include_state_inputs=True,
    )

    return kb_manager, kb_system


def render_keyboard_hints_collapsible(
    manager: ZoneManager,
    container_id: str = "align-demo-kb-hints",
) -> Any:
    """Render keyboard shortcut hints in a collapsible DaisyUI collapse."""
    hints = render_keyboard_hints(
        manager,
        include_navigation=True,
        include_zone_switch=False,
        badge_style="outline",
        container_id=container_id,
        use_icons=False
    )

    return Details(
        Summary(
            "Keyboard Shortcuts",
            cls=combine_classes(collapse_title, font_size.sm, font_weight.medium)
        ),
        Div(
            hints,
            cls=collapse_content
        ),
        cls=combine_classes(collapse, collapse_modifiers.arrow, bg_dui.base_200)
    )


# =============================================================================
# Mock Source Service
# =============================================================================

class MockSourceService:
    """Mock source service that maps record_ids to audio file paths."""

    def __init__(self, path_map: Dict[str, str]):
        self._path_map = path_map

    def get_transcription_by_id(self, record_id: str, provider_id: str) -> Any:
        """Return mock source block with media path."""
        from dataclasses import dataclass

        @dataclass
        class MockBlock:
            media_path: str

        path = self._path_map.get(record_id, "")
        return MockBlock(media_path=path)


# =============================================================================
# Init Handler Wrapper (Simplified - Demo Mode)
# =============================================================================

def create_demo_init_wrapper(
    urls: AlignmentUrls,
) -> Callable:
    """Create wrapper for align init that builds KB system (demo mode)."""

    async def wrapped_init(
        state_store: SQLiteWorkflowStateStore,
        workflow_id: str,
        source_service: MockSourceService,
        alignment_service: AlignmentService,
        request,
        sess,
        urls: AlignmentUrls,
        visible_count: int = DEFAULT_VISIBLE_COUNT,
        card_width: int = DEFAULT_CARD_WIDTH,
    ):
        """Wrapped init that adds KB system and chrome."""
        # Call pure domain handler
        result: AlignInitResult = await _handle_align_init(
            state_store, workflow_id, source_service, alignment_service,
            request, sess, urls, visible_count, card_width,
        )

        # Build single-zone KB system
        kb_manager, kb_system = build_single_zone_kb_system(urls)

        # OOB swap for keyboard system container
        kb_system_oob = Div(
            kb_system.script,
            kb_system.hidden_inputs,
            kb_system.action_buttons,
            id=DemoHtmlIds.KEYBOARD_SYSTEM,
            hx_swap_oob="innerHTML"
        )

        # Hints OOB
        hints_oob = Div(
            render_keyboard_hints_collapsible(kb_manager),
            id=DemoHtmlIds.SHARED_HINTS,
            hx_swap_oob="innerHTML"
        )

        # Settings modal
        settings_modal, settings_trigger = render_card_stack_settings_modal(
            ALIGN_CS_CONFIG, ALIGN_CS_IDS,
            current_count=result.visible_count,
            card_width=result.card_width,
        )

        # Toolbar OOB (settings trigger + speed selector + auto-play toggle)
        toolbar_oob = Div(
            settings_trigger,
            render_align_toolbar(speed_url=urls.speed_change),
            id=DemoHtmlIds.SHARED_TOOLBAR,
            hx_swap_oob="innerHTML"
        )

        # Settings modal OOB
        settings_modal_oob = Div(
            settings_modal,
            id=DemoHtmlIds.SETTINGS_MODAL,
            hx_swap_oob="innerHTML"
        )

        # Footer OOB
        footer_oob = Div(
            render_align_footer_content(result.chunks, result.focused_index),
            id=DemoHtmlIds.SHARED_FOOTER,
            hx_swap_oob="innerHTML"
        )

        # Mini-stats badge OOB
        mini_stats_oob = Span(
            render_align_mini_stats_text(result.chunks),
            id=DemoHtmlIds.MINI_STATS,
            cls=combine_classes(badge, badge_styles.ghost, badge_sizes.sm),
            hx_swap_oob="true",
        )

        return (
            result.column_body, kb_system_oob, hints_oob,
            toolbar_oob, settings_modal_oob, footer_oob, mini_stats_oob,
        )

    return wrapped_init


# =============================================================================
# Demo Page Renderer
# =============================================================================

def render_demo_page(
    urls: AlignmentUrls,
) -> Callable:
    """Create the demo page content factory."""

    def page_content():
        """Render the demo page with card stack column."""

        # Column header
        header = Div(
            Span(
                "VAD Alignment",
                cls=combine_classes(
                    font_size.sm, font_weight.bold,
                    uppercase, tracking.wide,
                    text_tiers.muted
                )
            ),
            Span(
                "--",
                id=DemoHtmlIds.MINI_STATS,
                cls=combine_classes(badge, badge_styles.ghost, badge_sizes.sm)
            ),
            id=DemoHtmlIds.COLUMN_HEADER,
            cls=combine_classes(
                flex_display, justify.between, items.center,
                chrome.column_header,
            )
        )

        # Column content (loading state with auto-trigger)
        from cjm_fasthtml_card_stack.components.states import render_loading_state

        content = Div(
            render_loading_state(ALIGN_CS_IDS, message="Loading VAD chunks..."),
            Div(
                hx_post=urls.init,
                hx_trigger="load",
                hx_target=f"#{AlignmentHtmlIds.COLUMN_CONTENT}",
                hx_swap="outerHTML"
            ),
            id=AlignmentHtmlIds.COLUMN_CONTENT,
            cls=combine_classes(grow(), overflow.hidden, flex_display, flex_direction.col, p(4))
        )

        # Column
        column_cls = combine_classes(
            w.full, max_w._4xl, m.x.auto,
            min_h(0),
            flex_display, flex_direction.col,
            panels.structural_container,
            overflow.hidden,
            transition.all, duration._200,
            ring(1), "ring-primary",
        )

        column = Div(
            header,
            content,
            id=DemoHtmlIds.COLUMN,
            cls=column_cls
        )

        # Placeholder chrome
        hints = Div(
            P("Keyboard hints will appear here after initialization.",
              cls=combine_classes(font_size.sm, text_tiers.muted)),
            id=DemoHtmlIds.SHARED_HINTS,
            cls=str(p(2))
        )

        toolbar = Div(
            P("Toolbar will appear here after initialization.",
              cls=combine_classes(font_size.sm, text_tiers.muted)),
            id=DemoHtmlIds.SHARED_TOOLBAR,
            cls=str(p(2))
        )

        # Settings modal container (populated by init handler)
        settings_modal_container = Div(id=DemoHtmlIds.SETTINGS_MODAL)

        footer = Div(
            P("Footer with progress will appear here after initialization.",
              cls=combine_classes(font_size.sm, text_tiers.muted)),
            id=DemoHtmlIds.SHARED_FOOTER,
            cls=combine_classes(
                chrome.column_footer,
                flex_display, justify.center, items.center,
            )
        )

        # Keyboard system container (empty initially, populated by init handler)
        kb_container = Div(id=DemoHtmlIds.KEYBOARD_SYSTEM)

        return Div(
            # Header
            Div(
                H1("VAD Alignment Demo",
                   cls=combine_classes(font_size._3xl, font_weight.bold)),
                P(
                    "Navigate VAD chunks with keyboard. Audio plays automatically on navigation.",
                    cls=combine_classes(text_tiers.secondary, m.b(2))
                ),
            ),

            # Shared chrome
            hints,
            toolbar,

            # Content area
            Div(
                column,
                cls=combine_classes(
                    grow(),
                    min_h(0),
                    flex_display,
                    flex_direction.col,
                    overflow.hidden,
                    p(1),
                )
            ),

            # Footer
            footer,

            # Keyboard system container
            kb_container,

            # Settings modal container
            settings_modal_container,

            id=DemoHtmlIds.CONTAINER,
            cls=combine_classes(
                container, max_w._5xl, m.x.auto,
                h.full,
                flex_display, flex_direction.col,
                p(4), p.x(2), p.b(0)
            )
        )

    return page_content


# =============================================================================
# Main Application
# =============================================================================

def main():
    """Initialize the alignment demo and start the server."""
    print("\n" + "=" * 70)
    print("Initializing cjm-transcript-vad-align Demo")
    print("=" * 70)

    # Initialize FastHTML app
    APP_ID = "txvadaln"

    app, rt = fast_app(
        pico=False,
        hdrs=[*get_daisyui_headers(), create_theme_persistence_script()],
        title="VAD Alignment Demo",
        htmlkw={'data-theme': 'light'},
        session_cookie=f'session_{APP_ID}_',
        secret_key=f'{APP_ID}-demo-secret',
    )

    # Mount vendored static assets (SoundTouch worklet for pitch-preserving speed)
    mount_web_audio_static(app)

    router = APIRouter(prefix="")

    # -------------------------------------------------------------------------
    # Set up state store
    # -------------------------------------------------------------------------
    temp_db = Path(tempfile.gettempdir()) / "cjm_transcript_vad_align_demo_state.db"
    state_store = SQLiteWorkflowStateStore(temp_db)
    workflow_id = "align-demo"

    print(f"  State store: {temp_db}")
    print(f"  Test audio files: {len(TEST_AUDIO_PATHS)}")
    for i, p in enumerate(TEST_AUDIO_PATHS):
        print(f"    [{i}] {p.name}")

    # -------------------------------------------------------------------------
    # Set up plugin manager and load VAD plugin
    # -------------------------------------------------------------------------
    print("\n[Plugin System]")
    plugin_manager = PluginManager(scheduler=SafetyScheduler())

    # Discover plugins from JSON manifests
    plugin_manager.discover_manifests()

    # Load the Silero VAD plugin
    vad_plugin_name = "cjm-media-plugin-silero-vad"
    vad_meta = plugin_manager.get_discovered_meta(vad_plugin_name)
    if vad_meta:
        try:
            success = plugin_manager.load_plugin(vad_meta, {})
            status = "loaded" if success else "failed"
            print(f"  {vad_plugin_name}: {status}")
        except Exception as e:
            print(f"  {vad_plugin_name}: error - {e}")
    else:
        print(f"  {vad_plugin_name}: not found")

    # Create services — map each audio file to a unique record_id
    path_map = {f"demo-source-{i}": str(p) for i, p in enumerate(TEST_AUDIO_PATHS)}
    source_service = MockSourceService(path_map=path_map)
    alignment_service = AlignmentService(plugin_manager, vad_plugin_name)

    # Initialize selection state with multiple demo sources
    selected_sources = [
        {"record_id": f"demo-source-{i}", "provider_id": "demo-provider"}
        for i in range(len(TEST_AUDIO_PATHS))
    ]

    def init_demo_state(sess):
        """Initialize demo state for session (always overwrites selection)."""
        session_id = get_session_id(sess)
        workflow_state = state_store.get_state(workflow_id, session_id)
        if "step_states" not in workflow_state:
            workflow_state["step_states"] = {}
        workflow_state["step_states"]["selection"] = {
            "selected_sources": selected_sources
        }
        state_store.update_state(workflow_id, session_id, workflow_state)

    # -------------------------------------------------------------------------
    # Audio serving route
    # -------------------------------------------------------------------------
    audio_router = APIRouter(prefix="/audio")

    @audio_router
    def audio_src(path: str = None):
        """Serve audio file for Web Audio API playback."""
        if path and Path(path).exists():
            return FileResponse(path, media_type="audio/mpeg")
        # Fallback to test audio if no path specified
        if TEST_AUDIO_PATH.exists():
            return FileResponse(str(TEST_AUDIO_PATH), media_type="audio/mpeg")
        from fasthtml.common import Response
        return Response(status_code=404, content="Audio file not found")

    audio_src_url = audio_src.to()

    # -------------------------------------------------------------------------
    # Set up alignment routes
    # -------------------------------------------------------------------------
    align_routers, align_urls, align_routes = init_alignment_routers(
        state_store=state_store,
        workflow_id=workflow_id,
        source_service=source_service,
        alignment_service=alignment_service,
        prefix="/align",
        audio_src_url=audio_src_url,
    )

    # Create wrapped init handler
    wrapped_init = create_demo_init_wrapper(align_urls)

    # Override the init route with our wrapped version
    init_router = APIRouter(prefix="/align/workflow")

    @init_router
    async def init(request, sess):
        """Initialize alignment with KB system."""
        init_demo_state(sess)
        return await wrapped_init(
            state_store, workflow_id, source_service, alignment_service,
            request, sess, urls=align_urls,
        )

    # -------------------------------------------------------------------------
    # Page routes
    # -------------------------------------------------------------------------
    page_content = render_demo_page(align_urls)

    @router
    def index(request, sess):
        """Demo homepage."""
        init_demo_state(sess)
        return handle_htmx_request(request, page_content)

    # -------------------------------------------------------------------------
    # Register routes
    # -------------------------------------------------------------------------
    register_routes(app, router, audio_router, init_router, *align_routers)

    # Debug output
    print("\n" + "=" * 70)
    print("Registered Routes:")
    print("=" * 70)
    for route in app.routes:
        if hasattr(route, 'path'):
            print(f"  {route.path}")
    print("=" * 70)
    print("Demo App Ready!")
    print("=" * 70 + "\n")

    return app


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    app = main()

    port = 5035
    host = "0.0.0.0"
    display_host = 'localhost' if host in ['0.0.0.0', '127.0.0.1'] else host

    print(f"Server: http://{display_host}:{port}")
    print()
    print("Controls:")
    print("  Arrow Up/Down     - Navigate VAD chunks (auto-plays audio)")
    print("  Ctrl+Up/Down      - Page up/down")
    print("  Ctrl+Shift+Up     - Jump to first chunk")
    print("  Ctrl+Shift+Down   - Jump to last chunk")
    print("  [ / ]             - Adjust viewport width")
    print()

    timer = threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}"))
    timer.daemon = True
    timer.start()

    uvicorn.run(app, host=host, port=port)
