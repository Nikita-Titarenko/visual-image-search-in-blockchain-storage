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
  imageRegistry: '0xEB7E73bC98943BfC382035F1D97ff484a8BA2485',
  licensingAndPayment: '0xA76B3778F95D649225591ea00ED69eDCFf586A69',
  modelAndIndexAudit: '0x08C053531D54A5496646c5443db9E0F06A9F27D0',
};