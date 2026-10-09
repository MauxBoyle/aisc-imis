from aisc_imis.app import main


def test_main_logs_greeting(capfd):
    main()
    captured = capfd.readouterr()
    assert "Hello from aisc_imis!" in captured.err
