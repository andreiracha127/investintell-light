/** Tick from the livefeed worker; source === "sim" is discarded by the parser. */
export interface Tick {
  symbol: string;
  price: number;
  size: number;
  time: string;
}
