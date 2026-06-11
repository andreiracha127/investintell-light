import { isRangePreset, type RangePreset } from "@/lib/api/client";
import { StockAnalysisView } from "@/components/stocks/StockAnalysisView";

export default async function StockAnalysisPage({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { ticker } = await params;
  const { range } = await searchParams;
  const initialRange: RangePreset = isRangePreset(range) ? range : "1Y";

  return (
    <StockAnalysisView
      ticker={decodeURIComponent(ticker).toUpperCase()}
      initialRange={initialRange}
    />
  );
}
