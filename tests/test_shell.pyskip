from pathlib import Path
from vpn_passthrough.shell import run, mkdir
from pytest import mark, fixture, TempPathFactory


@fixture(scope="session")
def temp_folder_path(tmp_path_factory: TempPathFactory):
    return tmp_path_factory.mktemp("tests")


@mark.parametrize("sudo", [True, False])
def test_run(sudo: bool, temp_folder_path: Path):
    file_path = temp_folder_path / "test.txt"

    run(["touch", str(file_path)], sudo=sudo)
    assert file_path.exists()
 
    run(["rm", str(file_path)], sudo=sudo)
    assert not file_path.exists()


def test_mkdir(temp_folder_path: Path):
    folder_path = temp_folder_path / "test.d"
    mkdir(folder_path)
    assert folder_path.exists()
    assert folder_path.is_dir()