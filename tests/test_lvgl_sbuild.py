from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess


def _load_lvgl_sbuild():
    script = Path(__file__).resolve().parents[1] / "packages" / "lvgl" / "sbuild.py"
    spec = spec_from_file_location("lvgl_sbuild", script)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_enable_lv_conf_turns_on_template_and_disables_examples():
    module = _load_lvgl_sbuild()
    text = module.enable_lv_conf(
        "#ifndef LV_CONF_H\n"
        "#if 0 /*Set it to \"1\" to enable the content*/\n"
        "#define LV_BUILD_EXAMPLES 1\n"
        "#define LV_BUILD_DEMOS 1\n"
        "#endif\n"
    )
    assert "#if 1" in text
    assert "#define LV_BUILD_EXAMPLES 0" in text
    assert "#define LV_BUILD_DEMOS 0" in text
    assert "#define LV_BUILD_EXAMPLES 1" not in text


def test_lvgl_sbuild_configures_static_library(tmp_path, monkeypatch):
    module = _load_lvgl_sbuild()
    source = tmp_path / "source"
    work = tmp_path / "work"
    stage = tmp_path / "stage"
    source.mkdir()
    (source / "lv_conf_template.h").write_text(
        "#if 0\n#define LV_BUILD_EXAMPLES 1\n#define LV_BUILD_DEMOS 1\n#endif\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SMART_BUILD_SOURCE_DIR", str(source))
    monkeypatch.setenv("SMART_BUILD_WORK_DIR", str(work))
    monkeypatch.setenv("SMART_BUILD_STAGE_DIR", str(stage))
    monkeypatch.setenv("SMART_BUILD_TARGET", "aarch64-linux-musleabi")
    monkeypatch.setenv("CC", "aarch64-linux-musleabi-gcc")
    monkeypatch.setenv("CXX", "aarch64-linux-musleabi-g++")
    monkeypatch.setenv("AR", "aarch64-linux-musleabi-ar")
    monkeypatch.setenv("RANLIB", "aarch64-linux-musleabi-ranlib")

    commands = []

    def fake_run(command, cwd, env=None, check=False, **kwargs):
        commands.append(tuple(command))
        if command and command[0] == "cmake" and "--install" in command:
            dest = Path(env["DESTDIR"])
            headers = dest / "usr/include/lvgl"
            headers.mkdir(parents=True)
            (headers / "lvgl.h").write_text("/* lvgl */\n", encoding="utf-8")
            library = dest / "usr/lib/liblvgl.a"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"!<arch>\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert module.main() == 0

    configure = next(command for command in commands if command and command[0] == "cmake" and "-S" in command)
    assert "-DBUILD_SHARED_LIBS=OFF" in configure
    assert "-DCONFIG_LV_BUILD_EXAMPLES=OFF" in configure
    assert "-DCONFIG_LV_BUILD_DEMOS=OFF" in configure
    assert (stage / "usr/include/lvgl/lvgl.h").is_file()
    assert (stage / "usr/include/lvgl/lv_conf.h").is_file()
    assert (stage / "usr/lib/liblvgl.a").is_file()
    assert "#define LV_BUILD_EXAMPLES 0" in (source / "lv_conf.h").read_text(encoding="utf-8")
