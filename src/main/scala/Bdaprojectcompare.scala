import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.functions._
import org.apache.spark.ml.Transformer
import org.apache.spark.ml.feature.VectorAssembler
import org.apache.spark.ml.classification.{DecisionTreeClassifier, LogisticRegression, RandomForestClassifier}
import org.apache.spark.ml.evaluation.MulticlassClassificationEvaluator
import org.apache.spark.storage.StorageLevel
import scala.collection.mutable.ArrayBuffer
import scala.util.Try

// Top-level case class (needed so Spark can turn results into a DataFrame)
case class ModelResult(model: String, f1: Double, precision: Double, recall: Double, train_seconds: Double)

/**
 * Model comparison + hyper-parameter tuning on a SAMPLE of the cleaned 22.1 GB data.
 * Usage:  spark-submit --class BDAProjectCompare ... /app/app.jar [sampleFraction]
 * Default sampleFraction = 0.01 (1 percent). Increase it for a bigger, slower run.
 */
object BDAProjectCompare {
  def main(args: Array[String]): Unit = {
    val fraction = if (args.nonEmpty) args(0).toDouble else 0.01

    val spark = SparkSession.builder().appName("BDAProjectCompare").getOrCreate()
    spark.conf.set("spark.sql.files.ignoreCorruptFiles", "true")
    import spark.implicits._
    spark.sparkContext.setLogLevel("WARN")

    // ---------- 1. Parse + clean (same logic as BDAProjectTrain) ----------
    val rawLines = spark.read.textFile("hdfs://namenode:9000/bda_project/raw/weather/*.gz")

    val parsed = rawLines.flatMap { line =>
      Try {
        val windRaw = line.substring(65, 69)
        val tempRaw = line.substring(87, 92)
        val wind = if (windRaw == "9999") None else Some(windRaw.toDouble / 10.0)
        val temp = if (tempRaw == "+9999") None else Some(tempRaw.toDouble / 10.0)
        (wind, temp)
      }.toOption
    }.toDF("wind_speed", "temperature")

    val labeled = parsed
      .filter($"temperature".isNotNull && $"wind_speed".isNotNull)
      .withColumn("fire_risk", when($"temperature" > 28 && $"wind_speed" > 5, 1.0).otherwise(0.0))

    val assembler = new VectorAssembler()
      .setInputCols(Array("temperature", "wind_speed"))
      .setOutputCol("features")
      .setHandleInvalid("skip")

    // ---------- 2. Sample, split, CACHE ----------
    val sampled = assembler.transform(labeled)
      .select("features", "fire_risk")
      .sample(withReplacement = false, fraction, seed = 42)

    val Array(trainDF, testDF) = sampled.randomSplit(Array(0.8, 0.2), seed = 42)

    // Cache: every model below re-uses these DataFrames instead of re-reading 22 GB of gzip
    trainDF.persist(StorageLevel.MEMORY_AND_DISK)
    testDF.persist(StorageLevel.MEMORY_AND_DISK)
    println(s"=== Sample fraction = $fraction | train rows = ${trainDF.count()} | test rows = ${testDF.count()} ===")

    // ---------- 3. Helpers ----------
    def metric(pred: DataFrame, name: String): Double =
      new MulticlassClassificationEvaluator()
        .setLabelCol("fire_risk").setPredictionCol("prediction")
        .setMetricName(name).evaluate(pred)

    def run(name: String)(fit: => Transformer): ModelResult = {
      val t0 = System.nanoTime()
      val model = fit
      val secs = (System.nanoTime() - t0) / 1e9
      val pred = model.transform(testDF)
      val r = ModelResult(name, metric(pred, "f1"), metric(pred, "weightedPrecision"),
        metric(pred, "weightedRecall"), secs)
      println(f"[done] ${r.model}%-34s F1=${r.f1}%.4f  P=${r.precision}%.4f  R=${r.recall}%.4f  time=${r.train_seconds}%.1fs")
      r
    }

    val results = ArrayBuffer[ModelResult]()

    // ---------- 4. Model comparison ----------
    results += run("Logistic Regression") {
      new LogisticRegression().setLabelCol("fire_risk").setFeaturesCol("features").setMaxIter(50).fit(trainDF)
    }
    results += run("Decision Tree (depth 5)") {
      new DecisionTreeClassifier().setLabelCol("fire_risk").setFeaturesCol("features").setMaxDepth(5).fit(trainDF)
    }

    // ---------- 5. Random Forest tuning grid: numTrees x maxDepth ----------
    for (trees <- Seq(20, 50, 100); depth <- Seq(3, 5, 10)) {
      results += run(s"Random Forest (trees=$trees, depth=$depth)") {
        new RandomForestClassifier().setLabelCol("fire_risk").setFeaturesCol("features")
          .setNumTrees(trees).setMaxDepth(depth).fit(trainDF)
      }
    }

    // ---------- 6. Final table (copy these numbers into the slides) ----------
    println("\n=== MODEL COMPARISON (sorted by F1) ===")
    results.sortBy(r => -r.f1).foreach { r =>
      println(f"${r.model}%-36s F1=${r.f1}%.4f  Precision=${r.precision}%.4f  Recall=${r.recall}%.4f  Time=${r.train_seconds}%.1fs")
    }

    results.toSeq.toDF().orderBy(desc("f1"))
      .coalesce(1).write.mode("overwrite").option("header", "true")
      .csv("file:///app/output/model_comparison")

    trainDF.unpersist()
    testDF.unpersist()
    spark.stop()
  }
}