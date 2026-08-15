from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .company_parser import parse_company_lookup_requests
from .company_research import research_company
from .enrichment import discover_official_site
from .ingestion import frame_to_operations
from .pipeline import ClassificationPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify companies from payment operations")
    parser.add_argument("--input", help="Input XLSX workbook or CSV file")
    parser.add_argument("--output", help="Path for the classified output workbook")
    parser.add_argument("--offline", action="store_true", help="Disable website discovery and verification")
    parser.add_argument("--parse-only", action="store_true", help="Extract companies and create a tax-ID research queue only")
    parser.add_argument("--lookup-output", help="Company research queue JSON file; required with --parse-only")
    parser.add_argument("--research", action="store_true", help="Extract companies and verify each one across public sources")
    parser.add_argument("--research-output", help="JSON file containing public-source facts and statuses")
    parser.add_argument("--max-companies", type=int, default=5, help="Maximum companies to research in one run; default: 5")
    parser.add_argument("--discover-sites", action="store_true", help="Discover official websites for confirmed research records")
    parser.add_argument("--research-input", help="JSON file created by --research")
    parser.add_argument("--site-output", help="JSON file containing official website discovery results")
    args = parser.parse_args()
    if args.parse_only:
        if not args.input:
            parser.error("--input is required with --parse-only")
        if not args.lookup_output:
            parser.error("--lookup-output is required with --parse-only")
        frame = pd.read_excel(args.input, sheet_name="Классификация_без_ответов")
        operations, warnings = frame_to_operations(frame, "classification")
        requests = parse_company_lookup_requests(operations)
        Path(args.lookup_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.lookup_output).write_text(
            json.dumps({"source": str(args.input), "parse_warnings": warnings, "requests": [x.to_dict() for x in requests]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Complete: {len(operations)} operations and {len(requests)} company research requests")
        return
    if args.research:
        if not args.input:
            parser.error("--input is required with --research")
        if not args.research_output:
            parser.error("--research-output is required with --research")
        if args.max_companies < 1:
            parser.error("--max-companies must be at least 1")
        frame = pd.read_excel(args.input, sheet_name="Классификация_без_ответов")
        operations, warnings = frame_to_operations(frame, "classification")
        requests = parse_company_lookup_requests(operations)
        records = [research_company(request) for request in requests[:args.max_companies]]
        Path(args.research_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.research_output).write_text(
            json.dumps({"source": str(args.input), "parse_warnings": warnings, "records": [x.to_dict() for x in records]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        confirmed = sum(x.status == "confirmed" for x in records)
        print(f"Complete: researched {len(records)} companies, confirmed {confirmed}, review required for {len(records) - confirmed}")
        return
    if args.discover_sites:
        if not args.research_input or not args.site_output:
            parser.error("--research-input and --site-output are required with --discover-sites")
        payload = json.loads(Path(args.research_input).read_text(encoding="utf-8"))
        results = []
        for record in payload.get("records", [])[:args.max_companies]:
            facts = record.get("canonical_facts", {})
            legal_name, inn = facts.get("legal_name"), record.get("inn")
            if record.get("status") != "confirmed" or not legal_name:
                results.append({"lookup_id": record.get("lookup_id"), "inn": inn, "status": "not_run", "reason": "The legal company name was not confirmed by the research workflow."})
                continue
            result = discover_official_site(legal_name, inn, online=True)
            results.append({"lookup_id": record.get("lookup_id"), "inn": inn, "legal_name": legal_name, **result.model_dump()})
        Path(args.site_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.site_output).write_text(json.dumps({"source": args.research_input, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        confirmed = sum(x.get("status") == "confirmed" for x in results)
        print(f"Complete: checked {len(results)} companies and confirmed {confirmed} official websites")
        return
    if not args.input or not args.output:
        parser.error("--input and --output are required for classification")
    result = ClassificationPipeline(online=not args.offline).classify_excel(args.input, args.output)
    print(f"Complete: {result['operations']} operations, {result['companies']} companies and {len(result['parse_warnings'])} parse warnings")


if __name__ == "__main__":
    main()
