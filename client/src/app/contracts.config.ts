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
  imageRegistry: '0x66949832428959A4759bE7c34a662dC3170d2294',
  licensingAndPayment: '0x9B2A32Af9f646647EA0c4d3386033Ab5033Ae2D0',
  modelAndIndexAudit: '0x40915402424b6c105327a3Dc53a920dff0b1d94a',
};