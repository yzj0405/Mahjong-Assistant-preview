package com.example.ai_assist.service

import android.annotation.SuppressLint
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import com.example.ai_assist.MainActivity
import com.example.ai_assist.R

class FloatingControlService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var floatingWidget: View
    private lateinit var params: WindowManager.LayoutParams

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    override fun onCreate() {
        super.onCreate()

        floatingWidget = LayoutInflater.from(this).inflate(R.layout.layout_floating_widget, null)
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager

        val layoutFlag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            WindowManager.LayoutParams.TYPE_PHONE
        }

        params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutFlag,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )

        params.gravity = Gravity.TOP or Gravity.START
        params.x = 0
        params.y = 100

        windowManager.addView(floatingWidget, params)
        setupWidgetTouchListener()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        intent?.let {
            val hand = it.getStringExtra("hand")
            val melds = it.getStringExtra("melds")
            val suggestions = it.getStringExtra("suggestions")

            floatingWidget.findViewById<TextView>(R.id.tv_floating_hand).text = hand
            floatingWidget.findViewById<TextView>(R.id.tv_floating_melds).text = melds
            floatingWidget.findViewById<TextView>(R.id.tv_floating_suggestions).text = suggestions
        }
        return START_NOT_STICKY
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun setupWidgetTouchListener() {
        val dragHandle = floatingWidget.findViewById<FrameLayout>(R.id.floating_widget_drag_handle)

        dragHandle.setOnTouchListener(object : View.OnTouchListener {
            private var initialX: Int = 0
            private var initialY: Int = 0
            private var initialTouchX: Float = 0f
            private var initialTouchY: Float = 0f
            private val CLICK_THRESHOLD = 10

            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> {
                        initialX = params.x
                        initialY = params.y
                        initialTouchX = event.rawX
                        initialTouchY = event.rawY
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        val dX = event.rawX - initialTouchX
                        val dY = event.rawY - initialTouchY
                        if (kotlin.math.abs(dX) < CLICK_THRESHOLD && kotlin.math.abs(dY) < CLICK_THRESHOLD) {
                            // It's a click, open the app
                            v.performClick()
                        }
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        params.x = initialX + (event.rawX - initialTouchX).toInt()
                        params.y = initialY + (event.rawY - initialTouchY).toInt()
                        windowManager.updateViewLayout(floatingWidget, params)
                        return true
                    }
                }
                return false
            }
        })

        dragHandle.setOnClickListener {
            val openAppIntent = Intent(this@FloatingControlService, MainActivity::class.java)
            openAppIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(openAppIntent)
            stopSelf()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::floatingWidget.isInitialized) {
            try {
                windowManager.removeView(floatingWidget)
            } catch (e: Exception) {
                // Ignore exceptions if view is already gone
            }
        }
    }
}