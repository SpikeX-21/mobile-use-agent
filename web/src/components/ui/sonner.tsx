// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// Licensed under the 【火山方舟】原型应用软件自用许可协议
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at 
//     https://www.volcengine.com/docs/82379/1433703
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner, ToasterProps } from "sonner"
import Image from "next/image"
import WarningIcon from "@/assets/toast-warning.svg"

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      position="top-center"
      duration={10000}
      toastOptions={{
        style: {
          padding: '8px 16px',
          fontSize: '14px',
          lineHeight: '20px',
          color: '#0C0D0E',
          gap: '4px',
        },
      }}
      icons={{
        warning: <Image src={WarningIcon} alt="warning" width={16} height={16} />,
      }}
      offset={{
        top: '32px'
      }}
      {...props}
    />
  )
}

export { Toaster }
