import io
import subprocess
import tarfile
from types import SimpleNamespace

import pytest

from smart_build.domains.package_sources import _apply_patches, _extract_archive, _run_command
from smart_build.errors import SmartBuildError


def _tar_member(name, content=None, linkname=None):
    member = tarfile.TarInfo(name)
    if linkname is not None:
        member.type = tarfile.SYMTYPE
        member.linkname = linkname
    else:
        payload = content.encode("utf-8")
        member.size = len(payload)
        return member, io.BytesIO(payload)
    return member, None


def test_archive_extractor_allows_internal_relative_symlink(tmp_path):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as handle:
        for name, content, linkname in (
            ("pkg/emptytest.c", "int main(void) { return 0; }\n", None),
            ("pkg/channel_droptest.c", None, "emptytest.c"),
        ):
            member, payload = _tar_member(name, content, linkname)
            handle.addfile(member, payload)

    prepared = tmp_path / "prepared"
    _extract_archive(archive, prepared, strip_root=True)

    assert (prepared / "channel_droptest.c").read_text(encoding="utf-8") == (
        "int main(void) { return 0; }\n"
    )
    assert not (prepared / "channel_droptest.c").is_symlink()


@pytest.mark.parametrize("linkname", ("/tmp/escape", "../../escape"))
def test_archive_extractor_rejects_links_escaping_archive_root(tmp_path, linkname):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as handle:
        member, payload = _tar_member("pkg/link", linkname=linkname)
        handle.addfile(member, payload)

    with pytest.raises(SmartBuildError, match="unsafe archive member link"):
        _extract_archive(archive, tmp_path / "prepared", strip_root=True)


def test_source_patch_is_applied_when_prepared_tree_is_inside_parent_git_repo(tmp_path):
    repository = tmp_path / "repository"
    prepared = repository / "build" / "sources" / "example-1.0"
    prepared.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(repository)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (prepared / "target.txt").write_text("before\n", encoding="utf-8")
    (prepared / "change.patch").write_text(
        "diff --git a/target.txt b/target.txt\n"
        "--- a/target.txt\n"
        "+++ b/target.txt\n"
        "@@ -1 +1 @@\n"
        "-before\n"
        "+after\n",
        encoding="utf-8",
    )
    config = SimpleNamespace(prepared=prepared, patches=("change.patch",))
    task = SimpleNamespace(log_path=tmp_path / "source.log")

    _apply_patches(config, _run_command, task, io.StringIO())

    assert (prepared / "target.txt").read_text(encoding="utf-8") == "after\n"
