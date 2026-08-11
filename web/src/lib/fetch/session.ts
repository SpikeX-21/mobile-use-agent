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

// Session亲和性管理工具

const FAAS_INSTANCE_KEY = 'mobile_use:agent_faas_instance_name';

export class SessionAffinityManager {
  /**
   * 获取当前存储的FaaS实例名称
   */
  static getFaasInstanceName(): string | null {
    if (typeof window !== 'undefined') {
      return sessionStorage.getItem(FAAS_INSTANCE_KEY);
    }
    return null;
  }

  /**
   * 存储FaaS实例名称
   */
  static setFaasInstanceName(instanceName: string): void {
    if (typeof window !== 'undefined') {
      sessionStorage.setItem(FAAS_INSTANCE_KEY, instanceName);
      console.log('✅ Session亲和性: 存储FaaS实例名称:', instanceName);
    }
  }

  /**
   * 清除FaaS实例名称
   */
  static clearFaasInstanceName(): void {
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem(FAAS_INSTANCE_KEY);
      console.log('🗑️ Session亲和性: 清除FaaS实例名称');
    }
  }

  /**
   * 检查是否有活跃的session亲和性
   */
  static hasActiveSession(): boolean {
    return this.getFaasInstanceName() !== null;
  }

  /**
   * 重置session（清除所有相关数据）
   */
  static resetSession(): void {
    this.clearFaasInstanceName();
    // 可以在这里添加其他需要清除的session相关数据
  }
}