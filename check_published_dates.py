import argparse

import main as eppr


def build_parser():
	parser = argparse.ArgumentParser(
		description="Check first-page image availability for e-paper dates."
	)
	parser.add_argument(
		'--paper',
		choices=sorted(eppr.PAPER_CONFIGS.keys()),
		default=None,
		help='paper source to check (default: both papers)'
	)
	parser.add_argument(
		'--date',
		type=eppr.parse_download_date,
		default=None,
		help='date to check, for example 05-05-2026 (default: today in IST)'
	)
	return parser


def main():
	parser = build_parser()
	args, _unknown = parser.parse_known_args()
	target_date = args.date or eppr.current_ist_date()
	papers = [args.paper] if args.paper else sorted(eppr.PAPER_CONFIGS.keys())

	for paper_name in papers:
		print("paper:", paper_name)
		print("target_date:", target_date.strftime("%Y-%m-%d"))
		if eppr.check_first_page_image_available(paper_name, target_date):
			print("image: OK")
		else:
			print("image: missing")
		print("")


if __name__ == "__main__":
	main()
