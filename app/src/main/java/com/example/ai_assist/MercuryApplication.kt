package com.example.ai_assist

import android.app.Application

/**
 * 手机端 Application
 * 移除了 AR 眼镜 MercurySDK 初始化，改为手机端适用
 */
class MercuryApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // 手机端无需初始化 MercurySDK (AR眼镜SDK)
        // 如需恢复AR眼镜功能，取消下方注释：
        // com.ffalcon.mercury.android.sdk.MercurySDK.init(this)
    }
}