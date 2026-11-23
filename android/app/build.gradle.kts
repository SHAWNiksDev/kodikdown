import java.util.Properties
import javax.inject.Inject

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

abstract class PrepareBrandResources : DefaultTask() {
    @get:InputDirectory
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val sourceDirectory: DirectoryProperty

    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @get:Inject
    abstract val fileSystem: FileSystemOperations

    @TaskAction
    fun prepare() {
        fileSystem.sync {
            from(sourceDirectory) {
                include("*.png")
                into("drawable-nodpi")
            }
            into(outputDirectory)
        }
    }
}

abstract class WriteSourceTrees : DefaultTask() {
    @get:Input
    abstract val sourceTrees: Property<String>

    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @TaskAction
    fun write() {
        val source = sourceTrees.get()
        check(source.matches(Regex("[a-f0-9]{40} [a-f0-9]{40}"))) {
            "Build the signed release with android/build.sh --release to record its source hashes."
        }
        outputDirectory.file("kodikdown-source-trees.txt").get().asFile.apply {
            check(parentFile.mkdirs() || parentFile.isDirectory) { "Could not create the APK assets directory." }
            writeText("$source\n")
        }
    }
}

androidComponents.onVariants { variant ->
    val variantName = variant.name.replaceFirstChar(Char::uppercaseChar)
    val brands = tasks.register<PrepareBrandResources>("prepare${variantName}BrandResources") {
        sourceDirectory.set(rootProject.layout.projectDirectory.dir("../src/kodikdown/gui/brands"))
    }
    variant.sources.res?.addGeneratedSourceDirectory(brands, PrepareBrandResources::outputDirectory)
}

androidComponents.onVariants(androidComponents.selector().withBuildType("release")) { variant ->
    val sourceHashes = tasks.register<WriteSourceTrees>("writeReleaseSourceTrees") {
        sourceTrees.set(providers.gradleProperty("kodikdownSourceTrees").orElse(""))
    }
    variant.sources.assets?.addGeneratedSourceDirectory(sourceHashes, WriteSourceTrees::outputDirectory)
}

val signingProperties = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
}
fun signingValue(name: String, environment: String): String? =
    providers.environmentVariable(environment).orNull ?: signingProperties.getProperty(name)
val releaseStore = signingValue("storeFile", "KODIKDOWN_KEYSTORE")
val releaseAlias = signingValue("keyAlias", "KODIKDOWN_KEY_ALIAS")
val releaseStorePassword = signingValue("storePassword", "KODIKDOWN_STORE_PASSWORD")
val releaseKeyPassword = signingValue("keyPassword", "KODIKDOWN_KEY_PASSWORD")
val releaseSigningReady = listOf(releaseStore, releaseAlias, releaseStorePassword, releaseKeyPassword)
    .all { !it.isNullOrBlank() }
val deviceQa = providers.gradleProperty("kodikdownDeviceQa").orNull == "true"

android {
    namespace = "com.shawniks.kodikdown"
    compileSdk = 35
    buildToolsVersion = "35.0.0"
    useLibrary("android.test.runner")
    useLibrary("android.test.base")

    defaultConfig {
        applicationId = "com.shawniks.kodikdown"
        minSdk = 24
        targetSdk = 34
        versionCode = 40600
        versionName = "4.6.0"

        testInstrumentationRunner = "android.test.InstrumentationTestRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    signingConfigs {
        if (releaseSigningReady) create("production") {
            storeFile = rootProject.file(releaseStore!!)
            storePassword = releaseStorePassword
            keyAlias = releaseAlias
            keyPassword = releaseKeyPassword
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            if (releaseSigningReady) signingConfig = signingConfigs.getByName("production")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
            if (deviceQa) applicationIdSuffix = ".deviceqa"
        }
        create("releaseSmoke") {
            initWith(getByName("release"))
            applicationIdSuffix = ".qa"
            versionNameSuffix = "-qa"
            matchingFallbacks += "release"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    bundle { language { enableSplit = false } }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }
}

tasks.matching { it.name == "packageRelease" }.configureEach {
    doFirst {
        check(releaseSigningReady) { "Release signing is missing. Configure keystore.properties or KODIKDOWN_* signing environment variables." }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.6")
    implementation("androidx.activity:activity-ktx:1.9.3")
    // API 24's framework muxer cannot preserve B-frame timestamps.
    implementation("androidx.media3:media3-muxer:1.5.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.1")
    testImplementation("junit:junit:4.13.2")
}
