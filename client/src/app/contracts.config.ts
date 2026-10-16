import { PUBLIC_ENV } from './public-env';

export interface ContractAddresses {
  imageRegistry: string;
  licensingAndPayment: string;
  modelAndIndexAudit: string;
}

export interface NetworkConfig {
  chainId: number;
  chainName: string;
  rpcUrl: string;
  blockExplorerUrl: string;
  nativeCurrency: {
    name: string;
    symbol: string;
    decimals: number;
  };
}

export const POLYGON_AMOY_CONFIG: NetworkConfig = {
  chainId: 80002,
  chainName: 'Polygon Amoy',
  rpcUrl: PUBLIC_ENV.polygonAmoyRpcUrl,
  blockExplorerUrl: 'https://amoy.polygonscan.com',
  nativeCurrency: {
    name: 'MATIC',
    symbol: 'MATIC',
    decimals: 18,
  },
};

export const DEFAULT_CONTRACT_ADDRESSES: ContractAddresses = {
  imageRegistry: '0xB1e92B954F96892781667d84cC79686BFe68386B',
  licensingAndPayment: '0xf8caa464E5010afEec817634F2C3d867718F6b9f',
  modelAndIndexAudit: '0x93F5cd2549c47076D628Ba6a52A062E262f5cfaf',
};