package defaultImplementations.numberOfCases;
import framework.CheckerInterface;

/**
 * Implementation of {@link framework.CheckerInterface#isSingularTestCase()}
 *
 * Use this if there is a single test case per file
 *
 * @author Philipp Hoffmann
 *
 */
public interface SingularTestCaseChecker extends CheckerInterface {
	/**
	 * Always returns true. Use this if there is a single test case per file
	 */
	default boolean isSingularTestCase() {
		return true;
	}
}
