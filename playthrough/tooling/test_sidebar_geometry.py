#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/sidebar_geometry.py.

The crop rectangle this module computes is where the sidebar clock is
read from, and the clock is what every frame's on-screen duration is
derived from.  Its failure mode is the quietest in the whole pipeline: a
crop taken from the wrong column does not raise, does not crash ffmpeg
and does not fail a count.  It simply matches no clock, so every reading
goes null, every duration collapses onto the 0.25 s floor, and the
finished film looks entirely plausible while its pacing means nothing.

That is why the module refuses to guess -- and why the refusals need
tests as much as the arithmetic does.  Every test here holds one of two
lines: the rectangle is DERIVED from the game's own configuration, and
where it cannot be derived the answer is a loud failure rather than a
plausible-looking number.

    python3 playthrough/tooling/test_sidebar_geometry.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED, AND WHY THESE NUMBERS
* THE CANONICAL CROP -- 36 cells x 8 px over a 240x67 grid at 1920x1080
  is 288x1072+1632+4, and the four-pixel y is the letterbox
  (1080 - 1072) // 2.  The engine's OWN default layout is 44 cells, not
  36, so the fresh-userdir crop is 352x1072+1568+4: both are asserted,
  because reading the wrong one of those two was a real defect.
* WHICH SIDEBAR IS ON SCREEN -- resolved from the game's own
  panel_options.json, falling back to the engine's constructor default
  legacy_labels_sidebar, with every substitution recorded in notes.  A
  panel options file that exists but cannot be believed RAISES rather
  than defaulting past, because defaulting there manufactures exactly
  the confident-but-wrong rectangle this module exists to prevent.
* TRUNCATE BEFORE MULTIPLY -- the engine divides the saved terminal by
  the scaling factor and multiplies back by font x factor, so a saved
  240x67 at factor 2 is a 120x33 logical grid in a 1920x1056 window.
  Multiplying first overshoots by the square of the factor.
* THE REFUSALS -- a sidebar wider than the window, a crop outside the X
  root, an unreadable widget width, an unrecognised sidebar position, a
  malformed options file, a narrowing band past the bottom of the
  column.  Each is a hard error with a reason.

WHAT IS DELIBERATELY NOT ASSERTED
No test asserts the live checkout's exact geometry: it legitimately
changes the moment the game writes an options file.  What is asserted
about the live tree is that the computation succeeds, that the width
came from the game's own widget JSON, and that the crop lies inside the
root.  Nothing is written anywhere outside a temporary directory.

Standard library only, plus the sibling module.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything written
# there.  This must precede the import below to affect it.
sys.dont_write_bytecode = True

try:
    import sidebar_geometry as geometry
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sidebar_geometry as geometry


# The headless contract: `Xvfb :99 -screen 0 1920x1080x24`.
ROOT_WIDTH = 1920
ROOT_HEIGHT = 1080

# The configuration this pipeline seeds: 240 columns x 8 px by 67 rows
# x 16 px, which is a 1920x1072 window inside the 1920x1080 root.
GRID_X = 240
GRID_Y = 67
FONT_WIDTH = 8
FONT_HEIGHT = 16
WINDOW_HEIGHT = GRID_Y * FONT_HEIGHT
LETTERBOX_Y = (ROOT_HEIGHT - WINDOW_HEIGHT) // 2

# The two widths that matter, and the crops they give.  custom_sidebar
# declares 36 cells; the engine's own default layout,
# legacy_labels_sidebar, declares 44 -- and cropping 288 px where 352
# belongs misses the clock entirely, in silence.
CUSTOM_CELLS = 36
LEGACY_CELLS = 44
CANONICAL_CROP = "288x1072+1632+4"
LEGACY_CROP = "352x1072+1568+4"

# The environment variables env.sh exports that this module reads.  Every
# test clears them, so a suite run inside a sourced shell behaves exactly
# as one run outside it.
ENVIRONMENT_KEYS = (
    "PLAYTHROUGH_REPO_ROOT",
    "PLAYTHROUGH_OPTIONS_JSON",
    "PLAYTHROUGH_PANEL_OPTIONS_JSON",
    "PLAYTHROUGH_CONFIG_DIR",
    "PLAYTHROUGH_SCREEN_WIDTH",
    "PLAYTHROUGH_SCREEN_HEIGHT",
    "PLAYTHROUGH_TERMINAL_X",
    "PLAYTHROUGH_TERMINAL_Y",
    "PLAYTHROUGH_FONT_WIDTH",
    "PLAYTHROUGH_FONT_HEIGHT",
)


@contextlib.contextmanager
def _environment(**values):
    """Set environment variables for a block, then restore them."""
    previous = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def setUpModule():
    """Silence the module's own WARNING stream for the whole suite.

    The warnings are how a substituted default stays visible to an
    operator, and they are asserted here through the `notes` list the
    same substitution appends to -- which is the checkable form of the
    same fact.  Letting them reach stderr as well would bury the test
    runner's own output in them.
    """
    geometry.LOG.addHandler(logging.NullHandler())
    geometry.LOG.propagate = False


class GeometryFixture(unittest.TestCase):
    """A temporary checkout holding only the files a test declares."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_geometry_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ui = os.path.join(self.root, "data", "json", "ui")
        os.makedirs(self.ui)
        source = os.path.join(self.root, "src")
        os.makedirs(source)
        # The two markers repo_root() proves a checkout by.
        with open(os.path.join(source, "path_info.cpp"), "w",
                  encoding="utf-8") as handle:
            handle.write("// a marker, not the engine\n")
        self.config = os.path.join(
            self.root, "playthrough", "userdir", "config")
        os.makedirs(self.config)
        self.options_json = os.path.join(self.config, "options.json")
        self.panel_options = os.path.join(
            self.config, "panel_options.json")
        self.sidebar_json = os.path.join(self.ui, "sidebar.json")
        cleared = {name: None for name in ENVIRONMENT_KEYS}
        self.env = _environment(**cleared)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    # -- fixture writers ---------------------------------------------

    def write_widgets(self, widgets, name="sidebar.json"):
        """Write a widget file and return its path."""
        path = os.path.join(self.ui, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(widgets, handle)
        return path

    def write_sidebar_widgets(self, *specs):
        """Write one `style: sidebar` widget per (id, width) pair."""
        return self.write_widgets([
            {"id": identifier, "style": "sidebar", "width": width}
            for identifier, width in specs])

    def write_options(self, values, shape="engine"):
        """Write an options file in one of the three accepted shapes."""
        if shape == "engine":
            data = [{"info": "an option", "default": "x",
                     "name": name, "value": value}
                    for name, value in values.items()]
        elif shape == "flat":
            data = dict(values)
        else:
            data = {name: {"value": value}
                    for name, value in values.items()}
        with open(self.options_json, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return self.options_json

    def write_panel_options(self, layout_id, wrap=True):
        """Write the engine's own panel options shape."""
        holder = {"current_layout_id": layout_id}
        with open(self.panel_options, "w", encoding="utf-8") as handle:
            json.dump([holder] if wrap else holder, handle)
        return self.panel_options

    def write_raw(self, path, text):
        """Write literal text to `path`, for the malformed cases."""
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    # -- convenience -------------------------------------------------

    def compute(self, **overrides):
        """Compute a geometry inside the temporary checkout."""
        arguments = {
            "repo_root_dir": self.root,
            "sidebar_json": self.sidebar_json,
            "options_json": self.options_json,
            "panel_options_json": self.panel_options,
            "screen_width": ROOT_WIDTH,
            "screen_height": ROOT_HEIGHT,
        }
        arguments.update(overrides)
        return geometry.compute_sidebar_geometry(**arguments)


class TestTheRectangle(unittest.TestCase):
    """A Rect describes real pixels, or it does not exist."""

    def test_the_geometry_string_is_the_imagemagick_form(self):
        rect = geometry.Rect(width=288, height=1072, x=1632, y=4)
        self.assertEqual(rect.geometry, CANONICAL_CROP)
        self.assertEqual(
            str(rect), CANONICAL_CROP,
            msg="so that interpolating a Rect into a command is safe")
        self.assertEqual(rect.right, 1920)
        self.assertEqual(rect.bottom, 1076)

    def test_a_rectangle_without_extent_is_refused(self):
        for width, height in ((0, 10), (10, 0), (-1, 10), (10, -1)):
            with self.subTest(width=width, height=height):
                with self.assertRaises(geometry.GeometryError):
                    geometry.Rect(width=width, height=height, x=0, y=0)

    def test_a_negative_origin_is_refused(self):
        for x, y in ((-1, 0), (0, -1)):
            with self.subTest(x=x, y=y):
                with self.assertRaises(geometry.GeometryError):
                    geometry.Rect(width=10, height=10, x=x, y=y)

    def test_a_non_integer_field_is_refused(self):
        for value in ("288", 288.0, True, None):
            with self.subTest(value=value):
                with self.assertRaises(geometry.GeometryError):
                    geometry.Rect(width=value, height=10, x=0, y=0)

    def test_containment_is_inclusive_of_the_edges(self):
        root = geometry.Rect(width=ROOT_WIDTH, height=ROOT_HEIGHT,
                             x=0, y=0)
        inside = geometry.Rect(width=288, height=1072, x=1632, y=4)
        self.assertTrue(root.contains(inside))
        self.assertTrue(
            root.contains(root),
            msg="a rectangle contains itself: the bound is inclusive")
        self.assertFalse(
            root.contains(
                geometry.Rect(width=288, height=1072, x=1633, y=4)),
            msg="one pixel past the right edge is outside")


class TestTheEngineGrid(unittest.TestCase):
    """TERMINAL_X is a physical cell count, not the logical grid."""

    def test_an_unscaled_grid_passes_through_untouched(self):
        self.assertEqual(
            geometry.engine_logical_grid(
                GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 1,
                ROOT_WIDTH, ROOT_HEIGHT),
            (GRID_X, GRID_Y, 1),
            msg=("every adjustment the engine makes lives inside "
                 "if( scaling_factor > 1 )"))

    def test_a_scaled_grid_is_divided_not_multiplied(self):
        self.assertEqual(
            geometry.engine_logical_grid(
                GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 2,
                ROOT_WIDTH, ROOT_HEIGHT),
            (120, 33, 2),
            msg=("a saved 240x67 at factor 2 is a 120x33 LOGICAL grid; "
                 "multiplying first overshoots by the square of the "
                 "factor"))

    def test_a_factor_too_large_for_the_display_is_reset_to_one(self):
        # 80 minimum columns x 8 px x factor 4 is 2560 px, wider than
        # the root, so the engine abandons the factor and recomputes the
        # terminal from the display size.
        notes = []
        self.assertEqual(
            geometry.engine_logical_grid(
                GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 4,
                ROOT_WIDTH, ROOT_HEIGHT, notes),
            (GRID_X, GRID_Y, 1),
            msg=("the engine resets the factor to 1 rather than "
                 "running a scaled grid it cannot fit"))
        self.assertTrue(
            any("resets the factor to 1" in note for note in notes),
            msg="and the reset is announced: %r" % notes)

    def test_a_terminal_wider_than_the_display_is_reduced(self):
        notes = []
        cols, rows, scale = geometry.engine_logical_grid(
            400, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 2,
            ROOT_WIDTH, ROOT_HEIGHT, notes)
        self.assertEqual(
            (cols, rows, scale), (120, 33, 2),
            msg=("400 cells x 8 px is 3200 px on a 1920 px display, so "
                 "the engine reduces the terminal to what fits"))
        self.assertTrue(notes, msg="and says it did")

    def test_the_trim_and_the_floor_are_the_engine_s_own(self):
        notes = []
        self.assertEqual(
            geometry.engine_logical_grid(
                165, 51, FONT_WIDTH, FONT_HEIGHT, 2,
                ROOT_WIDTH, ROOT_HEIGHT, notes)[:2],
            (82, 25),
            msg=("the engine trims the saved value to a multiple of "
                 "the factor before dividing: 165 -> 164 -> 82"))
        self.assertTrue(
            any("trims the terminal" in note for note in notes),
            msg=repr(notes))
        self.assertEqual(
            geometry.engine_logical_grid(
                80, 24, FONT_WIDTH, FONT_HEIGHT, 2,
                ROOT_WIDTH, ROOT_HEIGHT)[:2],
            (geometry.EVEN_MINIMUM_TERM_WIDTH,
             geometry.EVEN_MINIMUM_TERM_HEIGHT),
            msg=("and floors it at the engine's own minimum times the "
                 "factor, so the grid never goes below 80x24"))

    def test_a_non_positive_input_is_refused(self):
        for kwargs in ({"terminal_x": 0}, {"terminal_y": -1},
                       {"font_width": 0}, {"font_height": 0},
                       {"scaling_factor": 0}, {"screen_width": 0},
                       {"screen_height": 0}):
            with self.subTest(**kwargs):
                arguments = {
                    "terminal_x": GRID_X, "terminal_y": GRID_Y,
                    "font_width": FONT_WIDTH,
                    "font_height": FONT_HEIGHT,
                    "scaling_factor": 1, "screen_width": ROOT_WIDTH,
                    "screen_height": ROOT_HEIGHT,
                }
                arguments.update(kwargs)
                with self.assertRaises(geometry.GeometryError):
                    geometry.engine_logical_grid(**arguments)


class TestTheWindow(unittest.TestCase):
    """The window is centred in the root; the letterbox follows."""

    def test_the_contracted_window_is_1920x1072_at_the_letterbox(self):
        window = geometry.resolve_window(
            GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 1,
            ROOT_WIDTH, ROOT_HEIGHT)
        self.assertEqual(window.rect.geometry, "1920x1072+0+4")
        self.assertEqual(
            window.rect.y, LETTERBOX_Y,
            msg="(1080 - 1072) // 2 == 4, which is the letterbox")
        self.assertEqual((window.cols, window.rows), (GRID_X, GRID_Y))
        self.assertEqual(window.scale, 1)

    def test_a_scaled_window_reports_the_factor_in_force(self):
        window = geometry.resolve_window(
            GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 2,
            ROOT_WIDTH, ROOT_HEIGHT)
        self.assertEqual(window.rect.geometry, "1920x1056+0+12")
        self.assertEqual(
            window.scale, 2,
            msg=("the factor actually in force is returned, because "
                 "sizing the sidebar with an abandoned factor would "
                 "measure a window that was never made"))

    def test_a_window_larger_than_the_root_is_clamped_and_reported(self):
        notes = []
        window = geometry.resolve_window(
            GRID_X, 200, FONT_WIDTH, FONT_HEIGHT, 1,
            ROOT_WIDTH, ROOT_HEIGHT, notes)
        self.assertEqual(
            window.rect.height, ROOT_HEIGHT,
            msg=("the engine recomputes from the actual window when it "
                 "cannot honour the request, so the root is the honest "
                 "bound"))
        self.assertTrue(
            any("clamping to the root" in note for note in notes),
            msg=repr(notes))

    def test_the_rect_wrapper_takes_the_same_arguments(self):
        self.assertEqual(
            geometry.window_rect(
                GRID_X, GRID_Y, FONT_WIDTH, FONT_HEIGHT, 1,
                ROOT_WIDTH, ROOT_HEIGHT).geometry,
            "1920x1072+0+4")


class TestWhichSidebarIsOnScreen(GeometryFixture):
    """The layout comes from the game, or from the engine's default."""

    def test_the_persisted_layout_is_read_from_the_game_s_own_file(self):
        self.write_panel_options("custom_sidebar")
        notes = []
        self.assertEqual(
            geometry.read_current_layout_id(
                self.panel_options, notes, self.root),
            ("custom_sidebar", "panel_options.json"),
            msg=("panel_manager::serialize writes a one-element array "
                 "carrying current_layout_id, and that is where the "
                 "answer comes from"))
        self.assertEqual(
            notes, [],
            msg="reading the game's own choice is not a substitution")

    def test_a_bare_object_is_accepted_as_well_as_the_array(self):
        self.write_panel_options("custom_sidebar", wrap=False)
        self.assertEqual(
            geometry.read_current_layout_id(
                self.panel_options, None, self.root)[0],
            "custom_sidebar")

    def test_an_absent_file_yields_the_engine_default_with_a_note(self):
        notes = []
        layout, source = geometry.read_current_layout_id(
            self.panel_options, notes, self.root)
        self.assertEqual(
            (layout, source),
            (geometry.DEFAULT_LAYOUT_ID, "engine default"),
            msg=("a fresh userdir genuinely has no panel options, and "
                 "panel_manager's constructor default is "
                 "legacy_labels_sidebar on every non-Android build"))
        self.assertTrue(
            any("engine's own default" in note for note in notes),
            msg=repr(notes))

    def test_the_engine_default_is_the_44_cell_layout_not_the_36(self):
        self.assertEqual(
            geometry.DEFAULT_LAYOUT_ID, "legacy_labels_sidebar",
            msg=("reading custom_sidebar's 36 cells where the engine "
                 "draws 44 crops 64 px of the wrong column, in "
                 "silence"))
        self.assertEqual(geometry.CUSTOM_SIDEBAR_CELLS, CUSTOM_CELLS)
        self.assertNotIn(
            "DEFAULT_SIDEBAR_CELLS", vars(geometry),
            msg=("naming a width DEFAULT_ anything is what let a "
                 "36-cell crop stand in for a 44-cell sidebar"))

    def test_a_panel_options_file_that_cannot_be_believed_raises(self):
        cases = (
            ("[]", "an empty array"),
            ('["custom_sidebar"]', "an array of strings"),
            ('[{"other_key": 1}]', "an object with no layout id"),
            ('[{"current_layout_id": 5}]', "a non-string layout id"),
            ('[{"current_layout_id": "  "}]', "a blank layout id"),
            ("{not json", "text that is not JSON"),
        )
        for text, why in cases:
            with self.subTest(case=why):
                self.write_raw(self.panel_options, text)
                with self.assertRaises(geometry.GeometryError,
                                       msg=why):
                    geometry.read_current_layout_id(
                        self.panel_options, None, self.root)

    def test_the_layout_and_its_source_travel_with_the_geometry(self):
        self.write_sidebar_widgets(("legacy_labels_sidebar",
                                    LEGACY_CELLS))
        self.write_panel_options("legacy_labels_sidebar")
        result = self.compute()
        self.assertEqual(result.layout_id, "legacy_labels_sidebar")
        self.assertEqual(result.layout_source, "panel_options.json")
        self.assertEqual(
            result.sidebar_cells, LEGACY_CELLS,
            msg=("44 cells is only checkable if the reader knows which "
                 "of the shipped presets it came from"))

    def test_an_explicit_layout_override_is_recorded_as_one(self):
        self.write_sidebar_widgets(("custom_sidebar", CUSTOM_CELLS),
                                   ("legacy_labels_sidebar",
                                    LEGACY_CELLS))
        self.write_panel_options("legacy_labels_sidebar")
        result = self.compute(layout_id="custom_sidebar")
        self.assertEqual(result.layout_source, "layout id override")
        self.assertEqual(result.sidebar_cells, CUSTOM_CELLS)
        widget = self.compute(sidebar_widget_id="custom_sidebar")
        self.assertEqual(widget.layout_source, "widget id override")


class TestResolvingTheWidgetWidth(GeometryFixture):
    """The width comes from the widget the layout names, or not at all."""

    def test_the_named_widget_s_width_is_used(self):
        path = self.write_sidebar_widgets(
            ("custom_sidebar", CUSTOM_CELLS),
            ("legacy_labels_sidebar", LEGACY_CELLS))
        notes = []
        cells, used, source = geometry.resolve_sidebar_widget(
            "legacy_labels_sidebar", notes, self.root)
        self.assertEqual((cells, used), (LEGACY_CELLS,
                                         "legacy_labels_sidebar"))
        self.assertEqual(source, path)
        self.assertEqual(notes, [], msg="no substitution was needed")

    def test_the_whole_widget_tree_is_searched_not_one_file(self):
        self.write_widgets([], name="sidebar.json")
        self.write_sidebar_widgets_elsewhere = self.write_widgets(
            [{"id": "zenfs_sidebar", "style": "sidebar", "width": 32}],
            name="zenfs.json")
        cells, used, source = geometry.resolve_sidebar_widget(
            "zenfs_sidebar", None, self.root)
        self.assertEqual((cells, used), (32, "zenfs_sidebar"))
        self.assertTrue(
            source.endswith("zenfs.json"),
            msg=("the engine builds its layout map from every "
                 "style: sidebar widget in the whole data/json/ui "
                 "tree, so this module searches all of it"))

    def test_the_engine_s_own_fallbacks_are_used_and_announced(self):
        self.write_sidebar_widgets(
            ("legacy_classic_sidebar", 43),
            ("labels", 32))
        notes = []
        cells, used, _ = geometry.resolve_sidebar_widget(
            "a_layout_that_no_longer_exists", notes, self.root)
        self.assertEqual(
            (cells, used), (43, "legacy_classic_sidebar"),
            msg=("the engine falls back to legacy_classic_sidebar for "
                 "an id that no longer names a layout"))
        self.assertTrue(
            any("fallback layout" in note for note in notes),
            msg=("a crop taken from a layout other than the one asked "
                 "for is exactly the substitution a reader must see"))

    def test_the_second_fallback_is_the_engine_s_second(self):
        self.write_sidebar_widgets(("labels", 32))
        notes = []
        cells, used, _ = geometry.resolve_sidebar_widget(
            "absent_layout", notes, self.root)
        self.assertEqual((cells, used), (32, "labels"))
        self.assertTrue(notes)

    def test_the_first_widget_found_is_the_last_resort(self):
        self.write_sidebar_widgets(("some_theme_sidebar", 66))
        notes = []
        cells, used, _ = geometry.resolve_sidebar_widget(
            "absent_layout", notes, self.root)
        self.assertEqual((cells, used), (66, "some_theme_sidebar"))
        self.assertTrue(
            any("used the first sidebar widget found" in note
                for note in notes),
            msg=repr(notes))

    def test_no_sidebar_widget_anywhere_is_a_hard_failure(self):
        self.write_widgets([{"id": "not_a_sidebar", "style": "panel"}])
        with self.assertRaises(geometry.GeometryError) as bad:
            geometry.resolve_sidebar_widget("anything", None, self.root)
        self.assertIn("will not be guessed", str(bad.exception))

    def test_a_width_that_cannot_be_believed_is_refused(self):
        cases = (
            ({"id": "s", "style": "sidebar"}, "no width at all"),
            ({"id": "s", "style": "sidebar", "width": "36"},
             "a width that is a string"),
            ({"id": "s", "style": "sidebar", "width": 0},
             "a width of zero"),
            ({"id": "s", "style": "sidebar", "width": -8},
             "a negative width"),
            ({"id": "s", "style": "sidebar", "width": True},
             "a boolean width"),
        )
        for widget, why in cases:
            with self.subTest(case=why):
                self.write_widgets([widget])
                with self.assertRaises(geometry.GeometryError,
                                       msg=why):
                    geometry.resolve_sidebar_widget(
                        "s", None, self.root)

    def test_a_widget_file_of_the_wrong_shape_is_skipped_quietly(self):
        # The widget tree holds bare objects and other shapes the engine
        # simply ignores, so a file that is not an array of objects must
        # not stop the search.
        self.write_widgets({"id": "not_an_array"}, name="sidebar.json")
        self.write_widgets(
            [{"id": "custom_sidebar", "style": "sidebar",
              "width": CUSTOM_CELLS}], name="other.json")
        cells, used, _ = geometry.resolve_sidebar_widget(
            "custom_sidebar", None, self.root)
        self.assertEqual((cells, used), (CUSTOM_CELLS,
                                         "custom_sidebar"))

    def test_an_unparseable_widget_file_does_not_stop_the_search(self):
        self.write_raw(os.path.join(self.ui, "broken.json"), "{not json")
        self.write_sidebar_widgets(("custom_sidebar", CUSTOM_CELLS))
        cells, _, _ = geometry.resolve_sidebar_widget(
            "custom_sidebar", None, self.root)
        self.assertEqual(cells, CUSTOM_CELLS)


class TestReadingTheOptionsFile(GeometryFixture):
    """The engine writes strings; every shape is normalised to them."""

    def test_the_engine_s_own_array_shape_is_read(self):
        self.write_options({"TERMINAL_X": "240", "TERMINAL_Y": "67"})
        values = geometry.load_options(self.options_json, None,
                                       self.root)
        self.assertEqual(values["TERMINAL_X"], "240")
        self.assertEqual(values["TERMINAL_Y"], "67")

    def test_a_flat_or_nested_mapping_is_accepted_too(self):
        for shape in ("flat", "nested"):
            with self.subTest(shape=shape):
                self.write_options({"TERMINAL_X": 240}, shape=shape)
                self.assertEqual(
                    geometry.load_options(
                        self.options_json, None, self.root),
                    {"TERMINAL_X": "240"},
                    msg=("a hand-seeded or hand-inspected file still "
                         "works, and every value is normalised to the "
                         "string form the engine writes"))

    def test_a_boolean_is_normalised_to_the_engine_s_spelling(self):
        self.write_options({"SOUND_ENABLED": False}, shape="flat")
        self.assertEqual(
            geometry.load_options(self.options_json, None,
                                  self.root)["SOUND_ENABLED"],
            "false")

    def test_an_absent_file_is_an_ordinary_state(self):
        notes = []
        self.assertEqual(
            geometry.load_options(self.options_json, notes, self.root),
            {},
            msg=("a fresh userdir has no options.json until the game "
                 "has been launched once"))
        self.assertTrue(
            any("no options file at" in note for note in notes),
            msg="but the fallback is announced: %r" % notes)

    def test_a_file_that_cannot_be_believed_raises(self):
        cases = (
            ("{not json", "text that is not JSON"),
            ("17", "a bare number"),
            ('[{"name": "X"}]', "an entry with no value"),
            ('[{"value": "1"}]', "an entry with no name"),
            ('[{"name": 5, "value": "1"}]', "a non-string name"),
            ('["TERMINAL_X"]', "an array of strings"),
            ('{"TERMINAL_X": [240]}', "a value that is not a scalar"),
        )
        for text, why in cases:
            with self.subTest(case=why):
                self.write_raw(self.options_json, text)
                with self.assertRaises(geometry.GeometryError,
                                       msg=why):
                    geometry.load_options(
                        self.options_json, None, self.root)

    def test_an_absent_option_takes_its_documented_default(self):
        notes = []
        self.assertEqual(
            geometry.option_int({}, "TERMINAL_X", 80, notes), 80)
        self.assertTrue(
            any("using the engine's documented default" in note
                for note in notes))

    def test_an_option_that_is_not_an_integer_is_refused(self):
        for value in ("wide", "", "80.5"):
            with self.subTest(value=value):
                with self.assertRaises(geometry.GeometryError):
                    geometry.option_int(
                        {"TERMINAL_X": value}, "TERMINAL_X", 80)

    def test_an_option_of_zero_or_less_is_refused(self):
        for value in ("0", "-8"):
            with self.subTest(value=value):
                with self.assertRaises(geometry.GeometryError):
                    geometry.option_int(
                        {"TERMINAL_X": value}, "TERMINAL_X", 80)

    def test_an_out_of_range_option_is_used_but_reported(self):
        notes = []
        self.assertEqual(
            geometry.option_int({"TERMINAL_X": "5000"}, "TERMINAL_X",
                                80, notes,
                                geometry.TERMINAL_X_RANGE),
            5000,
            msg=("the options file is authoritative about what the "
                 "game is running with, so clamping it here would hide "
                 "a real misconfiguration"))
        self.assertTrue(
            any("outside the engine's declared range" in note
                for note in notes))

    def test_a_string_option_outside_its_domain_is_refused(self):
        with self.assertRaises(geometry.GeometryError) as bad:
            geometry.option_str(
                {"SIDEBAR_POSITION": "middle"}, "SIDEBAR_POSITION",
                "right", None, geometry.SIDEBAR_POSITIONS)
        self.assertIn(
            "which side the sidebar is drawn on", str(bad.exception),
            msg=("picking a side would be a coin toss dressed as a "
                 "computation"))

    def test_the_screen_size_comes_from_the_environment_contract(self):
        with _environment(PLAYTHROUGH_SCREEN_WIDTH="1600",
                          PLAYTHROUGH_SCREEN_HEIGHT="900"):
            self.assertEqual(
                geometry.resolve_screen_size(), (1600, 900))
        notes = []
        self.assertEqual(
            geometry.resolve_screen_size(notes=notes),
            (ROOT_WIDTH, ROOT_HEIGHT),
            msg="and falls back to the documented headless contract")
        self.assertTrue(notes)

    def test_a_screen_size_that_is_not_a_size_is_refused(self):
        with _environment(PLAYTHROUGH_SCREEN_WIDTH="wide"):
            with self.assertRaises(geometry.GeometryError):
                geometry.resolve_screen_size()
        with self.assertRaises(geometry.GeometryError):
            geometry.resolve_screen_size(width=0)

    def test_the_env_tier_beats_the_engine_first_launch_default(self):
        # A fresh userdir has no options.json, and the engine's own
        # first-launch default is 80x24 -- a 640x384 window -- whereas
        # capture runs at 240x67.  env.sh's contract is what bridges
        # that window, and the substitution is announced.
        self.write_sidebar_widgets(("legacy_labels_sidebar",
                                    LEGACY_CELLS))
        with _environment(PLAYTHROUGH_TERMINAL_X=str(GRID_X),
                          PLAYTHROUGH_TERMINAL_Y=str(GRID_Y),
                          PLAYTHROUGH_FONT_WIDTH=str(FONT_WIDTH),
                          PLAYTHROUGH_FONT_HEIGHT=str(FONT_HEIGHT)):
            result = self.compute()
        self.assertEqual(result.geometry, LEGACY_CROP)
        self.assertTrue(
            any("environment contract" in note
                for note in result.notes),
            msg=repr(result.notes))


class TestTheComputedCrop(GeometryFixture):
    """The whole computation, in the configuration that ships."""

    def setUp(self):
        super().setUp()
        self.write_sidebar_widgets(
            ("custom_sidebar", CUSTOM_CELLS),
            ("legacy_labels_sidebar", LEGACY_CELLS))
        self.write_options({
            "TERMINAL_X": str(GRID_X), "TERMINAL_Y": str(GRID_Y),
            "FONT_WIDTH": str(FONT_WIDTH),
            "FONT_HEIGHT": str(FONT_HEIGHT),
            "SCALING_FACTOR": "1", "SIDEBAR_POSITION": "right"})

    def test_the_canonical_crop_is_the_documented_rectangle(self):
        result = self.compute(layout_id="custom_sidebar")
        self.assertEqual(
            result.geometry, CANONICAL_CROP,
            msg=("36 cells x 8 px = 288 px, right-aligned in a "
                 "1920x1072 window at the 4 px letterbox"))
        self.assertEqual(
            result.notes, (),
            msg=("every value came from the game's own configuration, "
                 "so nothing was substituted"))
        self.assertFalse(result.used_fallbacks)

    def test_the_engine_default_layout_gives_the_wider_crop(self):
        self.write_panel_options("legacy_labels_sidebar")
        self.assertEqual(self.compute().geometry, LEGACY_CROP)

    def test_a_left_hand_sidebar_is_aligned_to_the_window(self):
        result = self.compute(layout_id="custom_sidebar",
                              position="left")
        self.assertEqual(result.geometry, "288x1072+0+4")
        self.assertEqual(result.position, "left")

    def test_the_position_is_read_from_the_options_file(self):
        self.write_options({
            "TERMINAL_X": str(GRID_X), "TERMINAL_Y": str(GRID_Y),
            "FONT_WIDTH": str(FONT_WIDTH),
            "FONT_HEIGHT": str(FONT_HEIGHT),
            "SIDEBAR_POSITION": "left"})
        self.assertEqual(
            self.compute(layout_id="custom_sidebar").geometry,
            "288x1072+0+4")

    def test_an_unrecognised_position_is_refused(self):
        with self.assertRaises(geometry.GeometryError):
            self.compute(layout_id="custom_sidebar", position="middle")

    def test_a_scaled_configuration_sizes_the_sidebar_by_the_factor(self):
        result = self.compute(layout_id="custom_sidebar",
                              scaling_factor=2)
        # 120x33 logical cells in a 1920x1056 window; the sidebar is 36
        # logical cells of 16 physical px.
        self.assertEqual(result.window.geometry, "1920x1056+0+12")
        self.assertEqual(result.geometry, "576x1056+1344+12")
        self.assertEqual(result.scaling_factor, 2)

    def test_a_sidebar_wider_than_the_window_is_refused(self):
        with self.assertRaises(geometry.GeometryError) as bad:
            self.compute(sidebar_cells=400)
        self.assertIn(
            "could not be read from it", str(bad.exception),
            msg=("a crop past the window edge cannot hold the clock, "
                 "and reporting it is the whole point"))

    def test_a_crop_outside_the_root_is_refused(self):
        # A window taller than the root is clamped, so the only way to
        # leave the root is a root smaller than the window the options
        # describe -- which is exactly the display-mismatch case.
        with self.assertRaises(geometry.GeometryError):
            self.compute(layout_id="custom_sidebar",
                         screen_width=320, screen_height=200,
                         terminal_x=GRID_X, terminal_y=GRID_Y,
                         sidebar_cells=400)

    def test_an_explicit_cell_count_overrides_the_widget(self):
        result = self.compute(sidebar_cells=40)
        self.assertEqual(result.sidebar_cells, 40)
        self.assertEqual(result.geometry, "320x1072+1600+4")

    def test_a_cell_count_that_spells_an_integer_is_accepted(self):
        # Every value in this pipeline arrives as text -- from an
        # environment variable, from a command line, or from the
        # engine's own options file, which stores integers as strings.
        # Coercing the string form is therefore the contract, not a
        # leak; what must not be tolerated is a value that does not
        # spell a whole positive count.
        self.assertEqual(
            self.compute(sidebar_cells="40").geometry,
            "320x1072+1600+4")

    def test_an_explicit_cell_count_must_still_be_a_cell_count(self):
        for value in (0, -1, 40.5, "40.5", "wide", "", True):
            with self.subTest(value=value):
                with self.assertRaises(geometry.GeometryError):
                    self.compute(sidebar_cells=value)

    def test_the_record_carries_every_input_it_was_derived_from(self):
        result = self.compute(layout_id="custom_sidebar")
        self.assertEqual(result.screen_width, ROOT_WIDTH)
        self.assertEqual(result.screen_height, ROOT_HEIGHT)
        self.assertEqual(result.terminal_x, GRID_X)
        self.assertEqual(result.terminal_y, GRID_Y)
        self.assertEqual(result.terminal_cols, GRID_X)
        self.assertEqual(result.terminal_rows, GRID_Y)
        self.assertEqual(result.font_width, FONT_WIDTH)
        self.assertEqual(result.font_height, FONT_HEIGHT)
        self.assertEqual(result.options_json, self.options_json)
        self.assertEqual(result.panel_options_json, self.panel_options)
        self.assertIn(
            "sidebar.json", result.sidebar_json,
            msg="including which widget file the width came from")

    def test_the_derivation_can_be_explained_line_by_line(self):
        text = self.compute(layout_id="custom_sidebar").describe()
        for expected in ("sidebar OCR crop derivation",
                         "grid origin y", "render grid",
                         CANONICAL_CROP, "36 cells", "1920x1080",
                         "substitutions made"):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_the_crop_string_helper_returns_only_the_geometry(self):
        self.assertEqual(
            geometry.sidebar_crop_geometry(
                repo_root_dir=self.root,
                sidebar_json=self.sidebar_json,
                options_json=self.options_json,
                panel_options_json=self.panel_options,
                layout_id="custom_sidebar",
                screen_width=ROOT_WIDTH,
                screen_height=ROOT_HEIGHT),
            CANONICAL_CROP)

    def test_whatever_root_is_returned_is_a_verified_checkout(self):
        self.assertEqual(geometry.repo_root(self.root), self.root)
        # A NOMINATED ROOT THAT IS NOT A CHECKOUT IS FATAL, not skipped.
        # An explicit argument or $PLAYTHROUGH_REPO_ROOT is an
        # instruction, and quietly answering it with this module's own
        # checkout would compute the crop from a different sidebar
        # layout and a different options file -- a well-formed rectangle
        # over the wrong pixels, which reads back as an unreadable clock
        # rather than as an error.
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(geometry.GeometryError) as bad:
                geometry.repo_root(empty)
        self.assertIn(
            empty, str(bad.exception),
            msg="the rejected path is named, so the fix is obvious")
        # And the derived root -- the only candidate that is a
        # derivation rather than an instruction -- still carries the
        # markers that make it a checkout.
        resolved = geometry.repo_root()
        for marker in (("data", "json", "ui"), ("src",)):
            self.assertTrue(
                os.path.isdir(os.path.join(resolved, *marker)),
                msg=("the invariant is that every root this function "
                     "returns carries the markers, however it was "
                     "reached"))
        self.assertTrue(
            os.path.isfile(
                os.path.join(resolved, "src", "path_info.cpp")))

    def test_no_checkout_among_the_candidates_is_a_hard_failure(self):
        original = geometry._looks_like_checkout
        geometry._looks_like_checkout = lambda path: False
        self.addCleanup(
            setattr, geometry, "_looks_like_checkout", original)
        with self.assertRaises(geometry.GeometryError) as bad:
            geometry.repo_root(self.root)
        message = str(bad.exception)
        self.assertIn("Cataclysm-DDA checkout", message)
        self.assertIn(
            self.root, message,
            msg=("naming the path that was rejected is what makes a "
                 "wrong root diagnosable rather than mysterious"))
        self.assertIn(os.path.join("src", "path_info.cpp"), message)

    def test_the_repository_root_may_come_from_the_environment(self):
        with _environment(PLAYTHROUGH_REPO_ROOT=self.root):
            self.assertEqual(geometry.repo_root(), self.root)


class TestNarrowingToRows(GeometryFixture):
    """Opt-in only: the clock's row is not fixed by configuration."""

    def setUp(self):
        super().setUp()
        self.write_sidebar_widgets(("custom_sidebar", CUSTOM_CELLS))
        self.write_options({
            "TERMINAL_X": str(GRID_X), "TERMINAL_Y": str(GRID_Y),
            "FONT_WIDTH": str(FONT_WIDTH),
            "FONT_HEIGHT": str(FONT_HEIGHT)})
        self.geometry = self.compute(layout_id="custom_sidebar")

    def test_the_full_column_is_the_default_answer(self):
        for first, count in ((None, None), (2, None), (None, 3)):
            with self.subTest(first_row=first, row_count=count):
                self.assertEqual(
                    geometry.narrow_to_rows(self.geometry, first,
                                            count),
                    self.geometry.rect,
                    msg=("the clock is drawn by the time_desc_label "
                         "widget at whatever row the sidebar puts it, "
                         "so the full column is the correct answer and "
                         "ocr_clock.py finds the row by pattern"))

    def test_a_band_is_measured_in_text_rows(self):
        band = geometry.narrow_to_rows(self.geometry, 2, 3)
        self.assertEqual(band.width, self.geometry.rect.width)
        self.assertEqual(band.height, 3 * FONT_HEIGHT)
        self.assertEqual(band.y, self.geometry.rect.y + 2 * FONT_HEIGHT)
        self.assertEqual(band.x, self.geometry.rect.x)

    def test_a_band_past_the_bottom_of_the_column_is_refused(self):
        with self.assertRaises(geometry.GeometryError) as bad:
            geometry.narrow_to_rows(self.geometry, GRID_Y - 1, 5)
        self.assertIn("past the bottom", str(bad.exception))

    def test_a_band_that_is_not_a_band_is_refused(self):
        for first, count in ((-1, 1), (True, 1), ("2", 1), (0, 0),
                             (0, -1), (0, "three"), (0, 2.5),
                             (0, True)):
            with self.subTest(first_row=first, row_count=count):
                with self.assertRaises(geometry.GeometryError):
                    geometry.narrow_to_rows(self.geometry, first, count)

    def test_a_row_count_that_spells_an_integer_is_accepted(self):
        # first_row is a strict int because it is only ever supplied in
        # code, while row_count shares the coercion every other
        # text-sourced count gets.  The asymmetry is real, so it is
        # pinned rather than papered over.
        self.assertEqual(
            geometry.narrow_to_rows(self.geometry, 2, "3").height,
            3 * FONT_HEIGHT)


class TestTheCommandLine(GeometryFixture):
    """stdout carries the geometry and nothing else."""

    def setUp(self):
        super().setUp()
        self.write_sidebar_widgets(
            ("custom_sidebar", CUSTOM_CELLS),
            ("legacy_labels_sidebar", LEGACY_CELLS))
        self.write_options({
            "TERMINAL_X": str(GRID_X), "TERMINAL_Y": str(GRID_Y),
            "FONT_WIDTH": str(FONT_WIDTH),
            "FONT_HEIGHT": str(FONT_HEIGHT)})

    def run_main(self, *argv):
        """Call main(argv) and return (status, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        base = ["--repo-root", self.root,
                "--sidebar-json", self.sidebar_json,
                "--options-json", self.options_json,
                "--panel-options-json", self.panel_options,
                "--screen-width", str(ROOT_WIDTH),
                "--screen-height", str(ROOT_HEIGHT)]
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = geometry.main(base + list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_stdout_is_exactly_the_geometry_and_a_newline(self):
        status, out, _ = self.run_main("--layout-id", "custom_sidebar")
        self.assertEqual(status, 0)
        self.assertEqual(
            out, CANONICAL_CROP + "\n",
            msg=('RECT="$(sidebar_geometry.py)" must need no parsing, '
                 "no trimming and no decoration stripped"))

    def test_the_engine_default_layout_is_used_with_no_arguments(self):
        status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), LEGACY_CROP)

    def test_the_derivation_goes_to_stderr_not_stdout(self):
        status, out, err = self.run_main(
            "--explain", "--layout-id", "custom_sidebar")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), CANONICAL_CROP)
        self.assertIn("sidebar OCR crop derivation", err)

    def test_a_failure_exits_one_and_writes_nothing_to_stdout(self):
        status, out, err = self.run_main("--sidebar-cells", "400")
        self.assertEqual(status, 1)
        self.assertEqual(
            out, "",
            msg=("a caller capturing stdout must not receive half an "
                 "answer"))
        self.assertIn("wide but the render grid", err)

    def test_the_narrowing_bounds_must_be_given_together(self):
        for argv in (("--first-row", "2"), ("--row-count", "3")):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as caught:
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.run_main(*argv)
                self.assertEqual(caught.exception.code, 2)

    def test_a_band_may_be_asked_for_explicitly(self):
        status, out, _ = self.run_main(
            "--layout-id", "custom_sidebar",
            "--first-row", "2", "--row-count", "3")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), "288x48+1632+36")

    def test_the_two_names_for_a_layout_are_not_both_accepted(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_main("--layout-id", "a", "--widget-id", "b")
        self.assertEqual(caught.exception.code, 2)

    def test_the_position_choices_are_the_engine_s_two(self):
        parser = geometry.build_parser()
        for action in parser._actions:
            if action.dest == "position":
                self.assertEqual(
                    list(action.choices),
                    list(geometry.SIDEBAR_POSITIONS))
                break
        else:  # pragma: no cover - the option exists
            self.fail("--position must exist")

    def test_verbose_is_accepted_and_changes_nothing_on_stdout(self):
        status, out, _ = self.run_main("-v", "--layout-id",
                                       "custom_sidebar")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), CANONICAL_CROP)


class TestTheLiveCheckout(unittest.TestCase):
    """The real repository must yield a usable crop, whatever its state.

    Deliberately not an assertion about the exact rectangle: it changes
    the moment the game writes an options file, and a test that pinned
    it would fail for the most ordinary reason there is.  What is
    asserted is that the computation SUCCEEDS against the real content
    tree, that the width came from the game's own widget JSON, and that
    the result is a crop that could actually be taken.
    """

    def test_the_crop_is_computable_and_inside_the_root(self):
        result = geometry.compute_sidebar_geometry()
        root = geometry.Rect(width=result.screen_width,
                             height=result.screen_height, x=0, y=0)
        self.assertTrue(
            root.contains(result.rect),
            msg=("capture targets the root, so a crop outside it could "
                 "not be taken: %s in %s"
                 % (result.geometry, root.geometry)))
        self.assertGreater(
            result.sidebar_cells, 0,
            msg="the width came from a real widget definition")
        self.assertTrue(
            os.path.isfile(result.sidebar_json),
            msg="and from a file that exists in this checkout")

    def test_the_shipped_widget_tree_declares_the_engine_default(self):
        cells, used, path = geometry.resolve_sidebar_widget(
            geometry.DEFAULT_LAYOUT_ID)
        self.assertEqual(
            used, geometry.DEFAULT_LAYOUT_ID,
            msg=("the engine's own default layout must exist in this "
                 "checkout, or the fresh-userdir crop is taken from a "
                 "fallback"))
        self.assertEqual(
            cells, LEGACY_CELLS,
            msg=("legacy_labels_sidebar declares 44 cells; a fresh "
                 "non-Android game therefore renders a 352 px sidebar, "
                 "not the 288 px custom_sidebar would imply"))
        self.assertTrue(os.path.isfile(path))

    def test_every_shipped_layout_is_asked_the_clock_question(self):
        """The crop is worthless if the layout draws no time.

        Asked of the LIVE content tree, because that is what a session
        records under, and the answer decides whether an alternate
        persisted preset may be continued at all.  Every preset this
        checkout ships reaches a widget rendering time_text or
        sundial_time_text -- the default reaches it through a copy-from
        chain, which is exactly the edge a walk over `widgets` alone
        misses.
        """
        for identifier in ("legacy_labels_sidebar", "custom_sidebar",
                           "legacy_classic_sidebar",
                           "legacy_compact_sidebar",
                           "legacy_labels_narrow_sidebar",
                           "my_labels_sidebar",
                           "my_labels_sidebar_cleaner",
                           "sidebar-mobile"):
            with self.subTest(layout=identifier):
                self.assertTrue(
                    geometry.layout_shows_the_clock(identifier),
                    msg=("%s ships in data/json/ui and must be "
                         "recordable" % identifier))

    def test_a_layout_that_is_not_there_shows_no_clock(self):
        """A name nothing defines is not a layout that draws a time."""
        self.assertFalse(
            geometry.layout_shows_the_clock("no_such_layout_at_all"))

    def test_the_clock_variables_are_the_engine_s_two(self):
        """Both are exact once the survivor carries a watch."""
        self.assertEqual(
            geometry.CLOCK_WIDGET_VARS,
            ("time_text", "sundial_time_text"))

    def test_the_module_imports_nothing_from_requirements(self):
        for name in ("moviepy", "PIL", "pytesseract", "numpy",
                     "imageio", "imageio_ffmpeg"):
            with self.subTest(package=name):
                self.assertNotIn(
                    name, vars(geometry),
                    msg=("the crop has to be computable on a bare "
                         "interpreter, because capture.sh asks for it "
                         "before anything is rendered"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
