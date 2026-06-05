import tempfile
import unittest
import sqlite3
from datetime import date
from unittest.mock import patch

import main


class DownloadCliTest(unittest.TestCase):
    def test_paper_config_has_separate_sources(self):
        self.assertEqual(main.PAPER_CONFIGS["sandhyanand"]["ppr_id"], "630")
        self.assertEqual(
            main.PAPER_CONFIGS["sandhyanand"]["image_base_url"],
            "https://sandhyanand.epapers.in/encyc/",
        )
        self.assertEqual(
            main.PAPER_CONFIGS["sandhyanand"]["image_base_urls"],
            [
                "https://sandhyanand.epapers.in/encyc/",
                "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/",
            ],
        )
        self.assertEqual(main.PAPER_CONFIGS["life365"]["ppr_id"], "635")
        self.assertEqual(
            main.PAPER_CONFIGS["life365"]["image_base_url"],
            "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/",
        )

    def test_build_page_image_url_uses_base_url_without_accumulating_pages(self):
        self.assertEqual(
            main.build_page_image_url(
                "https://sandhyanand.epapers.in/encyc/",
                "630",
                "2026_06_06",
                2,
            ),
            "https://sandhyanand.epapers.in/encyc/630/2026/06/06/Mpage_2.jpg",
        )

    def test_build_page_image_urls_supports_fallbacks(self):
        self.assertEqual(
            main.build_page_image_urls(
                [
                    "https://sandhyanand.epapers.in/encyc/",
                    "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/",
                ],
                "630",
                "2026_05_05",
                1,
            ),
            [
                "https://sandhyanand.epapers.in/encyc/630/2026/05/05/Mpage_1.jpg",
                "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/630/2026/05/05/Mpage_1.jpg",
            ],
        )

    def test_paper_config_can_be_resolved_by_ppr_id(self):
        self.assertEqual(
            main.resolve_paper_config(ppr_id="635")["image_base_url"],
            "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/",
        )

    def test_download_command_downloads_given_date_locally(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(
                main,
                "diver_program",
                return_value=(
                    "2026_06_06",
                    f"{output_dir}/630_2026_06_06.pdf",
                    output_dir,
                ),
            ) as diver_program:
                exit_code = main.main(
                    [
                        "download",
                        "06-06-2026",
                        "--paper",
                        "life365",
                        "--output-dir",
                        output_dir,
                    ]
                )

        self.assertEqual(exit_code, 0)
        diver_program.assert_called_once_with(
            date(2026, 6, 6),
            "635",
            download_directory=output_dir,
            base_url="https://idocuments.s3.ap-south-1.amazonaws.com/encyc/",
            base_urls=["https://idocuments.s3.ap-south-1.amazonaws.com/encyc/"],
        )

    def test_download_command_can_send_pdf_to_telegram(self):
        with tempfile.TemporaryDirectory() as output_dir:
            pdf_path = f"{output_dir}/635_2026_06_06.pdf"
            with patch.object(
                main,
                "diver_program",
                return_value=("2026_06_06", pdf_path, output_dir),
            ):
                with patch.object(main, "send_to_telegram") as send_to_telegram:
                    exit_code = main.main(
                        [
                            "download",
                            "06-06-2026",
                            "--paper",
                            "life365",
                            "--output-dir",
                            output_dir,
                            "--send-telegram",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        send_to_telegram.assert_called_once_with("L365_2026_06_06.pdf", pdf_path)

    def test_download_command_does_not_send_to_telegram_when_pdf_generation_fails(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(
                main,
                "diver_program",
                side_effect=RuntimeError("could not download image page from any source"),
            ):
                with patch.object(main, "send_to_telegram") as send_to_telegram:
                    exit_code = main.main(
                        [
                            "download",
                            "06-06-2026",
                            "--paper",
                            "life365",
                            "--output-dir",
                            output_dir,
                            "--send-telegram",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        send_to_telegram.assert_not_called()

    def test_send_latest_paper_downloads_sends_and_records_current_ist_date(self):
        with tempfile.TemporaryDirectory() as output_dir:
            db_path = f"{output_dir}/sent.db"
            pdf_path = f"{output_dir}/630_2026_06_05.pdf"
            folder_path = f"{output_dir}/630_2026_06_05"

            with patch.object(
                main,
                "current_ist_date",
                return_value=date(2026, 6, 5),
            ):
                with patch.object(main, "check_first_page_image_available", return_value=True):
                    with patch.object(
                        main,
                        "diver_program",
                        return_value=("2026_06_05", pdf_path, folder_path),
                    ) as diver_program:
                        with patch.object(main, "send_to_telegram") as send_to_telegram:
                            result = main.send_latest_paper(
                                "sandhyanand",
                                db_name=db_path,
                                download_directory=output_dir,
                                cleanup=False,
                            )

            self.assertEqual(result, "sent")
            diver_program.assert_called_once()
            send_to_telegram.assert_called_once_with("SND_2026_06_05.pdf", pdf_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT IsSent FROM SNDND WHERE DATE = ?", ("2026-06-05",))
            self.assertEqual(cursor.fetchone(), (1,))
            conn.close()

    def test_send_latest_paper_uses_explicit_date_when_given(self):
        with tempfile.TemporaryDirectory() as output_dir:
            db_path = f"{output_dir}/sent.db"
            pdf_path = f"{output_dir}/630_2026_05_05.pdf"
            folder_path = f"{output_dir}/630_2026_05_05"

            with patch.object(main, "current_ist_date") as current_ist_date:
                with patch.object(main, "check_first_page_image_available", return_value=True):
                    with patch.object(
                        main,
                        "diver_program",
                        return_value=("2026_05_05", pdf_path, folder_path),
                    ) as diver_program:
                        with patch.object(main, "send_to_telegram") as send_to_telegram:
                            result = main.send_latest_paper(
                                "sandhyanand",
                                target_date=date(2026, 5, 5),
                                db_name=db_path,
                                download_directory=output_dir,
                                cleanup=False,
                            )

            self.assertEqual(result, "sent")
            current_ist_date.assert_not_called()
            diver_program.assert_called_once()
            send_to_telegram.assert_called_once_with("SND_2026_05_05.pdf", pdf_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT IsSent FROM SNDND WHERE DATE = ?", ("2026-05-05",))
            self.assertEqual(cursor.fetchone(), (1,))
            conn.close()

    def test_send_latest_command_passes_explicit_date(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(main, "send_latest_paper", return_value="missing") as send_latest_paper:
                exit_code = main.main(
                    [
                        "send-latest",
                        "--paper",
                        "sandhyanand",
                        "--date",
                        "05-05-2026",
                        "--output-dir",
                        output_dir,
                    ]
                )

        self.assertEqual(exit_code, 0)
        send_latest_paper.assert_called_once_with(
            "sandhyanand",
            download_directory=output_dir,
            cleanup=True,
            target_date=date(2026, 5, 5),
        )

    def test_send_latest_paper_skips_when_current_date_already_sent(self):
        with tempfile.TemporaryDirectory() as output_dir:
            db_path = f"{output_dir}/sent.db"
            conn = sqlite3.connect(db_path)
            main.ensure_sent_table(conn, "LIFE365")
            main.mark_paper_sent(conn, "LIFE365", "2020-04-05")
            conn.close()

            with patch.object(
                main,
                "current_ist_date",
                return_value=date(2020, 4, 5),
            ):
                with patch.object(main, "diver_program") as diver_program:
                    with patch.object(main, "send_to_telegram") as send_to_telegram:
                        result = main.send_latest_paper(
                            "life365",
                            db_name=db_path,
                            download_directory=output_dir,
                        )

            self.assertEqual(result, "already_sent")
            diver_program.assert_not_called()
            send_to_telegram.assert_not_called()

    def test_send_latest_paper_skips_when_current_date_image_missing(self):
        with tempfile.TemporaryDirectory() as output_dir:
            db_path = f"{output_dir}/sent.db"

            with patch.object(
                main,
                "current_ist_date",
                return_value=date(2026, 6, 6),
            ):
                with patch.object(main, "check_first_page_image_available", return_value=False):
                    with patch.object(main, "diver_program") as diver_program:
                        with patch.object(main, "send_to_telegram") as send_to_telegram:
                            result = main.send_latest_paper(
                                "life365",
                                db_name=db_path,
                                download_directory=output_dir,
                            )

            self.assertEqual(result, "missing")
            diver_program.assert_not_called()
            send_to_telegram.assert_not_called()

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM LIFE365 WHERE DATE = ?", ("2026-06-06",))
            self.assertEqual(cursor.fetchone(), (0,))
            conn.close()


if __name__ == "__main__":
    unittest.main()
