import io
import tarfile

import pytest

from smart_build.domains.package_sources import _extract_archive
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
