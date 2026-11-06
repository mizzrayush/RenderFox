"""Defects to plant in `src/processing/preview_render.py`, one line at a time.

Run:  python -X utf8 tools/mutation_check.py tests/test_preview_render_contract.py tools/mutations_preview_render.py
      python -X utf8 tools/mutation_check.py tests/test_preview_render_contract.py tools/mutations_preview_render.py --list

The raster is the one part of this app that answers with pixels, so most of these defects are
invisible to any check that does not look at a picture: an inverted focal length, a dropped
minus sign in the extrinsic, a falloff that stopped dividing by distance squared. Each entry
therefore names the test that has to go red.

Four of them - a mesh painted as a point cloud, an eye behind what it looks at, a fitted eye
inside the model, an eye standing on its target - killed the suite instead of failing a test,
because Open3D takes the process down with it and a dead process names nothing. Those four are
caught through `SeamCase` in the suite, which drives `_extrinsic`, `_fit_distance`,
`_display_colors`, `_paint` and `_place` (through a control stand-in that only records what the
product writes) without opening a window. Two more - the all-background file and a one-pixel
silhouette - are caught through `WrittenFileCase`, which replaces the write and the capture so
the verdict rules are reached on purpose rather than by luck.
"""

MUTATIONS = [
    # ---- how the surface is handed to the raster --------------------------------------
    {
        'file': 'src/processing/preview_render.py',
        'find': "SURFACE_SHADE = 'Color'",
        'replace': "SURFACE_SHADE = 'Flat'",
        'expect': 'test_more_intensity_is_a_brighter_picture',
        'note': 'the engine shades by its own flat rule instead of by the vertex normals',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "SURFACE_COLOR = 'Color'",
        'replace': "SURFACE_COLOR = 'Mono'",
        'expect': 'test_the_lamp_colour_lands_in_the_pixels',
        'note': 'the lamp colour is thrown away on the way to the window',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        options.light_on = False',
        'replace': '        options.light_on = True',
        'expect': 'test_the_engine_head_light_is_never_turned_on',
        'note': 'the engine head light clips a dim lamp and a bright one to the same 255',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        geometry.vertex_colors = vectors',
        'replace': '        geometry.vertex_colors = o3d.utility.Vector3dVector('
                   'np.full_like(colors, 0.5))',
        'expect': 'test_more_intensity_is_a_brighter_picture',
        'note': 'every vertex is painted one flat grey, so no knob can be seen',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "    if kind == 'surface':",
        'replace': '    if False:',
        'expect': 'test_a_surface_is_painted_with_vertex_colours_and_not_point_colours',
        'note': 'a mesh is handed its colours as a point cloud, which a mesh does not read',
    },

    # ---- the three lamps ---------------------------------------------------------------
    {
        'file': 'src/processing/preview_render.py',
        'find': "    if light.kind == 'directional':",
        'replace': "    if light.kind == 'sun':",
        'expect': 'test_more_intensity_is_a_brighter_picture',
        'note': 'the default lamp kind is no longer a kind the renderer knows',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        return np.clip(normals @ direction, 0.0, 1.0) * float(light.intensity)',
        'replace': '        return np.abs(normals @ direction).clip(0.0, 1.0) '
                   '* float(light.intensity)',
        'expect': 'test_a_lamp_behind_the_model_is_darker_than_one_in_front',
        'note': 'the far side lights up as brightly as the near side',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "    if light.kind == 'point':",
        'replace': "    if light.kind == 'point_lamp':",
        'expect': 'test_a_point_lamp_gets_brighter_as_it_gets_closer',
        'note': 'a point lamp is refused by name it was never given',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        return cosine * (light.intensity / (safe * safe))',
        'replace': '        return cosine * light.intensity',
        'expect': 'test_a_point_lamp_gets_brighter_as_it_gets_closer',
        'note': 'the inverse-square falloff is gone, so distance changes nothing',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        inside = (spread >= cone).astype(float)',
        'replace': '        inside = np.ones_like(spread)',
        'expect': 'test_a_wider_cone_lights_more_of_the_picture_than_a_tight_one',
        'note': 'the cone angle is asked and then ignored',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        colors = np.clip(tint[None, :] * (lit[:, None] + float(light.ambient)),'
                ' 0.0, 1.0)',
        'replace': '        colors = np.clip(tint[None, :] * lit[:, None], 0.0, 1.0)',
        'expect': 'test_ambient_carries_the_picture_when_the_lamp_is_off',
        'note': 'ambient is dropped, so an unlit model is black rather than dim',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "    elif light is not None and kind == 'points':",
        'replace': '    elif False:',
        'expect': 'test_a_lamp_on_a_cloud_refuses_because_there_is_no_surface_to_light',
        'note': 'a cloud is lit by a lamp that has nothing to fall on',
    },

    # ---- display modes -----------------------------------------------------------------
    {
        'file': 'src/processing/preview_render.py',
        'find': "        elif geometry.has_colors():",
        'replace': '        elif False:',
        'expect': 'test_a_coloured_cloud_keeps_its_own_colours',
        'note': 'the colours in the file are replaced by the default grey',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if normals is None:',
        'replace': '        if False:',
        'expect': 'test_normals_mode_refuses_a_faceless_file',
        'note': 'the normals mode is offered for a file with no faces to take a normal from',
    },
    {
        'file': 'src/processing/preview_render.py',
        "find": "        axis = {'x_coordinate': 0, 'y_coordinate': 1, 'z_coordinate': 2, "
                "'height': 2}[mode]",
        "replace": "        axis = {'x_coordinate': 0, 'y_coordinate': 1, 'z_coordinate': 2, "
                   "'height': 0}[mode]",
        'expect': 'test_the_coordinate_maps_ramp_on_the_axis_their_names_promise',
        'note': 'the height map ramps along x, which is not the height of anything',
    },

    # ---- the camera --------------------------------------------------------------------
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if not (1.0 <= float(self.fov) <= 170.0):',
        'replace': '        if not (0.0 <= float(self.fov) <= 360.0):',
        'expect': 'test_a_field_of_view_too_tight_refuses',
        'note': 'any number is accepted as a camera angle',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    focal = (height / 2.0) / np.tan(np.radians(camera.fov) / 2.0)',
        'replace': '    focal = (height / 2.0) * np.tan(np.radians(camera.fov) / 2.0)',
        'expect': 'test_a_wide_lens_shrinks_the_model_and_a_tight_one_grows_it',
        'note': 'the lens does the opposite of the angle it was given',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    parameters.intrinsic.intrinsic_matrix = intrinsic',
        'replace': '    pass',
        'expect': 'test_the_field_of_view_is_written_into_the_matrix_that_is_live',
        'note': 'the matrix that is edited is not the matrix the window reads',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    intrinsic[0, 2] = width / 2.0',
        'replace': '    intrinsic[0, 2] = width / 4.0',
        'expect': 'test_the_pinhole_matrix_puts_the_principal_point_at_the_centre_of_the_frame',
        'note': 'the principal point is off to one side, so the model sits off centre',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    rotation = np.vstack([right, -vertical, forward])',
        'replace': '    rotation = np.vstack([right, vertical, forward])',
        'expect': 'test_the_extrinsic_rows_keep_the_sign_the_visualizer_expects',
        'note': 'the plain look-at basis makes the camera look backwards',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    matrix[:3, 3] = rotation @ (-eye)',
        'replace': '    matrix[:3, 3] = rotation @ eye',
        'expect': 'test_the_extrinsic_puts_the_eye_at_the_camera_origin_and_its_target_in_front',
        'note': 'the eye is placed behind everything it is supposed to look at',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    return radius / max(1e-6, np.sin(limiting / 2.0)) * 1.05',
        'replace': '    return radius / max(1e-6, np.sin(limiting / 2.0)) * 0.2',
        'expect': 'test_the_fitted_distance_projects_the_whole_bounding_sphere_inside_the_frame',
        'note': 'the fitted eye sits inside the model, so the frame is all surface',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if camera.fit:',
        'replace': '    if False:',
        'expect': 'test_fit_works_at_any_scale_the_pipeline_can_hand_it',
        'note': 'the bounding sphere is never consulted, so scale decides what is drawn',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '            direction = np.asarray(camera.position, float) - target',
        'replace': '            direction = np.asarray(camera.direction, float)',
        'expect': 'test_moving_the_eye_changes_the_frame',
        'note': 'the position the caller typed is discarded for a default vector',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if length < 1e-9:',
        'replace': '        if False:',
        'expect': 'test_a_fitted_camera_placed_on_the_point_it_looks_at_refuses',
        'note': 'a zero-length look direction is divided by instead of refused',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if camera.position is None:',
        'replace': '        if False:',
        'expect': 'test_an_unfitted_camera_must_say_where_the_eye_is',
        'note': 'an unfitted camera with no eye is handed None to numpy',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if float(np.linalg.norm(eye - target)) < 1e-9:',
        'replace': '        if False:',
        'expect': 'test_an_unfitted_camera_on_the_point_it_looks_at_refuses',
        'note': 'the eye standing on the target point is drawn rather than refused',
    },

    # ---- the window, the file, and what the verdict is allowed to claim -----------------
    {
        'file': 'src/processing/preview_render.py',
        'find': '        visualizer.destroy_window()',
        'replace': '        pass',
        'expect': 'test_the_window_is_always_destroyed_even_when_the_frame_raises',
        'note': 'the window this call opened is left open on this desktop',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': 'MIN_WINDOW_WIDTH = 148',
        'replace': 'MIN_WINDOW_WIDTH = 1',
        'expect': 'test_a_window_this_machine_will_not_open_is_resampled_and_said',
        'note': 'the floor the machine really enforces is no longer the floor the code says',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if (open_width, open_height) != (draw_width, draw_height):',
        'replace': '    if False:',
        'expect': 'test_a_window_this_machine_will_not_open_is_resampled_and_said',
        'note': 'the window that opened short is reported as the window that was asked for',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if (open_width, open_height) != (final_width, final_height):',
        'replace': '    if False:',
        'expect': 'test_an_ask_beyond_the_desktop_yields_the_ask_and_names_the_window',
        'note': 'the frame is never folded back to the size the caller asked for',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if (final_width, final_height) != (asked_width, asked_height):',
        'replace': '    if False:',
        'expect': 'test_an_absurd_ask_is_capped_and_says_what_the_cap_is',
        'note': 'the cap is applied in silence',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if (measured_width, measured_height) != (final_width, final_height):',
        'replace': '    if (measured_width, measured_height) != (asked_width, asked_height):',
        'expect': 'test_an_absurd_ask_is_capped_and_says_what_the_cap_is',
        'note': 'a capped picture is refused because it is not the number that was typed',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        return cloud, \'points\'',
        'replace': '        return None, None',
        'expect': 'test_a_faceless_ply_is_drawn_as_points',
        'note': 'a cloud is read as nothing and the file is refused',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if not os.path.isfile(geometry_path):',
        'replace': '    if False:',
        'expect': 'test_a_missing_model_refuses',
        'note': 'a model that is not on disk reaches the reader instead of being refused',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if extension not in IMAGE_FORMATS:',
        'replace': '    if False:',
        'expect': 'test_an_exr_is_refused_and_the_refusal_lists_what_this_build_can_write',
        'note': 'an encoder this build does not have is asked of Pillow anyway',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if geometry is None:',
        'replace': '    if False:',
        'expect': 'test_an_empty_geometry_file_refuses',
        'note': 'a file with neither triangles nor points is drawn as an empty scene',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if int(differs.sum()) == 0:',
        'replace': '    if False:',
        'expect': 'test_a_camera_aimed_away_from_the_model_is_a_refusal_not_an_empty_picture',
        'note': 'a frame of nothing but background is written and reported as a picture',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if covered == 0:',
        'replace': '    if False:',
        'expect': 'test_a_file_that_rereads_as_only_background_refuses',
        'note': 'the file on disk is no longer the thing the verdict checks',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "        if extension in ('jpg', 'jpeg'):",
        'replace': '        if False:',
        'expect': 'test_a_jpg_refuses_transparency_instead_of_losing_it_silently',
        'note': 'the alpha channel is dropped by an encoder that never carries one',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        transparent_pixels = int((seen_alpha == 0).sum())',
        'replace': '        transparent_pixels = 0',
        'expect': 'test_transparency_accounts_for_every_pixel_in_the_file',
        'note': 'the two pixel counts no longer have to add up to the picture',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '        if opaque != covered:',
        'replace': '        if opaque != transparent_pixels:',
        'expect': 'test_transparency_accounts_for_every_pixel_in_the_file',
        'note': 'the alpha check compares two counts that were never meant to match',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if not os.path.isdir(folder):',
        'replace': '    if False:',
        'expect': 'test_a_missing_folder_refuses_before_anything_is_drawn',
        'note': 'the folder is made by Pillow, or the failure is Pillow\'s, not this module\'s',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    rows = np.where(differs.any(axis=1))[0]',
        'replace': '    rows = np.where(differs.any(axis=0))[0]',
        'expect': 'test_the_silhouette_is_measured_from_the_pixels_not_from_the_bounds',
        'note': 'the silhouette height is taken across the columns',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "        'silhouette_width': int(columns[-1] - columns[0] + 1),",
        'replace': "        'silhouette_width': int(columns[-1] - columns[0]),",
        'expect': 'test_a_one_column_wide_silhouette_is_one_pixel_wide',
        'note': 'a one-pixel-wide model reports a silhouette of zero pixels wide',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': "        'coverage_percent': round(100.0 * covered / float(measured_width * "
                "measured_height), 2),",
        'replace': "        'coverage_percent': round(100.0 * covered / float(measured_width), 2),",
        'expect': 'test_a_fitted_frame_shows_the_model_and_not_a_fill_or_a_background',
        'note': 'the percentage is taken over a strip, not over the picture',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if should_cancel is not None and should_cancel():',
        'replace': '    if False:',
        'which': 1,
        'expect': 'test_a_stop_before_the_frame_writes_nothing',
        'note': 'a stop pressed first still opens a window and writes a file',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if should_cancel is not None and should_cancel():',
        'replace': '    if False:',
        'which': 2,
        'expect': 'test_a_stop_after_the_write_reports_the_file_that_is_on_disk',
        'note': 'a stop after the write hides the file that is on disk',
    },

    # ---- the multiple the caller asked for ---------------------------------------------
    # These four name the claim the suite has not yet made: nothing renders at supersample
    # today, so the arithmetic and its two sentences are unproved.
    {
        'file': 'src/processing/preview_render.py',
        'find': '    ceiling = MAX_WINDOW // max(1, final_width, final_height)',
        'replace': '    ceiling = MAX_WINDOW',
        'expect': 'test_a_supersample_that_will_not_fit_is_cut_and_says_so',
        'note': 'the multiple is no longer cut to what the ceiling can hold',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    samples = max(1, min(samples_asked, ceiling))',
        'replace': '    samples = samples_asked',
        'expect': 'test_a_supersample_that_will_not_fit_is_cut_and_says_so',
        'note': 'the number asked is reported whether or not the window could open at it',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if samples > 1:',
        'replace': '    if False:',
        'expect': 'test_supersample_draws_one_frame_at_the_multiple_and_reports_it',
        'note': 'the note stops saying which multiple ran',
    },
    {
        'file': 'src/processing/preview_render.py',
        'find': '    if samples_asked != samples:',
        'replace': '    if False:',
        'expect': 'test_a_supersample_that_will_not_fit_is_cut_and_says_so',
        'note': 'a cut multiple is applied without a word about it',
    },
]
