import { redirect } from "next/navigation";

/** Home = Stock Analysis of the default ticker. */
export default function Home() {
  redirect("/stocks/AAPL");
}
